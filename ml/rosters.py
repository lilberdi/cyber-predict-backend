"""Roster sync: current players of tracked teams from PandaScore, with history and transfers.

PandaScore only exposes the *current* roster, so history starts the first time we run.
Every sync diffs the fresh rosters against the open rows in team_rosters and records
joins, leaves and transfers (team A -> team B).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ml.config import PANDASCORE_BASE_URL, PANDASCORE_TOKEN
from ml.db import connect
from ml.pandascore import PandaScoreError

TRACKED_ELO_TOP = 150  # top teams by Elo ...
TRACKED_MIN_GAMES = 15  # ... with enough games to be real
BATCH = 100  # PandaScore per_page limit; one request covers 100 teams


@dataclass(frozen=True)
class Op:
    kind: str  # join | leave | transfer
    player: str  # external id
    from_team: int | None
    to_team: int | None


def plan_changes(
    open_rows: dict[str, int],
    desired: dict[str, list[int]],
    tracked: set[int],
    skip_leave_teams: set[int] = frozenset(),
) -> list[Op]:
    """open_rows: player -> team now. desired: player -> teams listing them (fresh API data).

    A player listed by several teams stays where they already are; otherwise the first wins.
    Players on a tracked team that no tracked team lists any more have left.
    """
    ops: list[Op] = []
    for player, teams in sorted(desired.items()):
        cur = open_rows.get(player)
        target = cur if cur in teams else teams[0]
        if cur == target:
            continue
        ops.append(Op("join" if cur is None else "transfer", player, cur, target))
    for player, team in sorted(open_rows.items()):
        if player not in desired and team in tracked and team not in skip_leave_teams:
            ops.append(Op("leave", player, team, None))
    return ops


def fetch_teams(ps_ids: list[int]) -> list[dict[str, Any]]:
    if not PANDASCORE_TOKEN:
        raise PandaScoreError("PANDASCORE_TOKEN is empty")
    headers = {"Authorization": f"Bearer {PANDASCORE_TOKEN}", "Accept": "application/json"}
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=25.0) as client:
        for i in range(0, len(ps_ids), BATCH):
            chunk = ps_ids[i : i + BATCH]
            resp = client.get(
                f"{PANDASCORE_BASE_URL}/csgo/teams",
                headers=headers,
                params={"filter[id]": ",".join(map(str, chunk)), "per_page": BATCH},
            )
            if resp.status_code >= 400:
                raise PandaScoreError(f"pandascore {resp.status_code}: {resp.text[:300]}")
            out.extend(resp.json())
    return out


def tracked_teams(cur) -> dict[int, int]:
    """db team id -> PandaScore team id for teams we keep rosters for."""
    cur.execute(
        """
        SELECT t.id, t.external_id FROM teams t
        WHERE t.external_id LIKE 'ps-team-%%' AND (
            t.id IN (SELECT team1_id FROM matches WHERE status IN ('upcoming','running')
                     UNION SELECT team2_id FROM matches WHERE status IN ('upcoming','running'))
            OR t.id IN (SELECT team_id FROM team_elo WHERE matches_played >= %s
                        ORDER BY rating DESC LIMIT %s))
        """,
        (TRACKED_MIN_GAMES, TRACKED_ELO_TOP),
    )
    return {int(r["id"]): int(r["external_id"].removeprefix("ps-team-")) for r in cur.fetchall()}


def _upsert_player(cur, p: dict[str, Any]) -> int:
    cur.execute(
        """
        INSERT INTO players (external_id, nickname, slug, first_name, last_name, nationality, birthday, image_url, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (external_id) DO UPDATE SET
            nickname = EXCLUDED.nickname,
            slug = COALESCE(EXCLUDED.slug, players.slug),
            first_name = COALESCE(EXCLUDED.first_name, players.first_name),
            last_name = COALESCE(EXCLUDED.last_name, players.last_name),
            nationality = COALESCE(EXCLUDED.nationality, players.nationality),
            birthday = COALESCE(EXCLUDED.birthday, players.birthday),
            image_url = COALESCE(EXCLUDED.image_url, players.image_url),
            updated_at = now()
        RETURNING id
        """,
        (f"ps-player-{p['id']}", p["name"], p.get("slug"), p.get("first_name"), p.get("last_name"),
         p.get("nationality"), p.get("birthday"), p.get("image_url")),
    )
    return int(cur.fetchone()["id"])


def sync_rosters(teams_payload: list[dict[str, Any]] | None = None) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            tracked = tracked_teams(cur)
            if not tracked:
                return {"tracked": 0, "joins": 0, "leaves": 0, "transfers": 0}
            by_ps = {ps: db for db, ps in tracked.items()}
            payload = teams_payload if teams_payload is not None else fetch_teams(sorted(by_ps))

            cur.execute("SELECT count(*) AS n FROM team_rosters")
            baseline = cur.fetchone()["n"] == 0  # first snapshot: do not flood the transfer feed

            desired: dict[str, list[int]] = {}
            players: dict[str, dict[str, Any]] = {}
            empty: set[int] = set()
            for team in payload:
                db_team = by_ps.get(int(team["id"]))
                if db_team is None:
                    continue
                active = [p for p in team.get("players") or [] if p.get("active", True) and p.get("name")]
                if not active:
                    empty.add(db_team)  # likely a data glitch: never mass-release a roster
                for p in active:
                    ext = f"ps-player-{p['id']}"
                    desired.setdefault(ext, []).append(db_team)
                    players[ext] = p

            cur.execute(
                """
                SELECT p.external_id, r.team_id FROM team_rosters r
                JOIN players p ON p.id = r.player_id WHERE r.left_at IS NULL
                """
            )
            open_rows = {r["external_id"]: int(r["team_id"]) for r in cur.fetchall()}
            ops = plan_changes(open_rows, desired, set(tracked), empty)

            pid = {ext: _upsert_player(cur, p) for ext, p in players.items()}
            counts = {"join": 0, "leave": 0, "transfer": 0}
            for op in ops:
                if op.player not in pid:
                    cur.execute("SELECT id FROM players WHERE external_id = %s", (op.player,))
                    pid[op.player] = int(cur.fetchone()["id"])
                player_id = pid[op.player]
                if op.from_team is not None:
                    cur.execute(
                        "UPDATE team_rosters SET left_at = now() WHERE player_id = %s AND left_at IS NULL", (player_id,)
                    )
                if op.to_team is not None:
                    cur.execute("INSERT INTO team_rosters (team_id, player_id) VALUES (%s, %s)", (op.to_team, player_id))
                counts[op.kind] += 1
                if not baseline:
                    cur.execute(
                        "INSERT INTO roster_changes (player_id, kind, from_team_id, to_team_id) VALUES (%s, %s, %s, %s)",
                        (player_id, op.kind, op.from_team, op.to_team),
                    )
        conn.commit()
    return {"tracked": len(tracked), "players": len(players), "baseline": baseline,
            "joins": counts["join"], "leaves": counts["leave"], "transfers": counts["transfer"]}
