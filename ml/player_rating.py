"""Team Impact Rating: an Elo for players built only from team results.

A team's strength is the mean rating of its five players, so a transfer changes the
strength of both teams. After a match every player of a roster moves by his own K
(newcomers move faster) times the same surprise (result - expected). Without per-player
match statistics this is the honest ceiling: it separates players only through roster
changes, not through who fragged better in a single game.

Ratings are seeded from the team Elo the first time a player appears and then updated
incrementally; a match is processed once (player_rating_history is the ledger).
"""

from __future__ import annotations

from ml.config import ELO_K, ELO_K_BOOST, ELO_K_N0, ELO_MARGIN_WEIGHT, ELO_START, ELO_TIER_WEIGHT
from ml.db import connect
from ml.elo import expected_score
from ml.features import tier_value

ROSTER_SIZE = 5
MIN_KNOWN_PLAYERS = 3  # skip the match if either side has fewer rostered players


def player_k(games: int) -> float:
    return ELO_K * (1.0 + ELO_K_BOOST / (1.0 + games / ELO_K_N0))


def pick_lineup(candidates: list[tuple[int, float, int]]) -> list[tuple[int, float, int]]:
    """candidates: (player_id, rating, games). Keep the five who actually play most."""
    return sorted(candidates, key=lambda c: (-c[2], -c[1], c[0]))[:ROSTER_SIZE]


def rate_match(
    lineup1: list[tuple[int, float, int]],
    lineup2: list[tuple[int, float, int]],
    team1_won: bool,
    margin: float = 0.0,
    tier: int = 2,
) -> dict[int, float]:
    """Returns player_id -> rating delta."""
    r1 = sum(c[1] for c in lineup1) / len(lineup1)
    r2 = sum(c[1] for c in lineup2) / len(lineup2)
    surprise = (1.0 if team1_won else 0.0) - expected_score(r1, r2)
    weight = (1.0 + ELO_MARGIN_WEIGHT * margin) * (1.0 + ELO_TIER_WEIGHT * (tier - 2) / 4.0)
    out: dict[int, float] = {}
    for pid, _, games in lineup1:
        out[pid] = player_k(games) * weight * surprise
    for pid, _, games in lineup2:
        out[pid] = -player_k(games) * weight * surprise
    return out


def _seed_players(cur) -> int:
    cur.execute(
        """
        INSERT INTO player_rating (player_id, rating, seed_rating)
        SELECT DISTINCT ON (r.player_id) r.player_id, COALESCE(e.rating, %s), COALESCE(e.rating, %s)
        FROM team_rosters r LEFT JOIN team_elo e ON e.team_id = r.team_id
        WHERE NOT EXISTS (SELECT 1 FROM player_rating pr WHERE pr.player_id = r.player_id)
        ORDER BY r.player_id, r.joined_at
        """,
        (ELO_START, ELO_START),
    )
    return cur.rowcount


def _lineup(cur, team_id: int, when, state: dict[int, tuple[float, int]]) -> list[tuple[int, float, int]]:
    cur.execute(
        """
        SELECT player_id FROM team_rosters
        WHERE team_id = %s AND joined_at <= %s AND (left_at IS NULL OR left_at > %s)
        """,
        (team_id, when, when),
    )
    cands = []
    for row in cur.fetchall():
        pid = int(row["player_id"])
        if pid in state:
            cands.append((pid, state[pid][0], state[pid][1]))
    return pick_lineup(cands)


def update_ratings() -> dict:
    """Process finished matches that fall inside the roster era and are not rated yet."""
    with connect() as conn:
        with conn.cursor() as cur:
            seeded = _seed_players(cur)
            cur.execute("SELECT player_id, rating, matches_played FROM player_rating")
            state = {int(r["player_id"]): (float(r["rating"]), int(r["matches_played"])) for r in cur.fetchall()}
            if not state:
                conn.commit()
                return {"seeded": 0, "matches_rated": 0, "matches_skipped": 0}

            cur.execute(
                """
                SELECT m.id, m.team1_id, m.team2_id, m.winner_team_id, m.scheduled_at,
                       m.score1, m.score2, m.tournament_tier
                FROM matches m
                WHERE m.status = 'finished' AND m.winner_team_id IS NOT NULL AND m.voided_reason IS NULL AND m.scheduled_at IS NOT NULL
                  AND m.scheduled_at >= (SELECT min(joined_at) FROM team_rosters)
                  AND NOT EXISTS (SELECT 1 FROM player_rating_history h WHERE h.match_id = m.id)
                ORDER BY m.scheduled_at, m.id
                """
            )
            matches = cur.fetchall()
            rated = skipped = 0
            for m in matches:
                l1 = _lineup(cur, m["team1_id"], m["scheduled_at"], state)
                l2 = _lineup(cur, m["team2_id"], m["scheduled_at"], state)
                if len(l1) < MIN_KNOWN_PLAYERS or len(l2) < MIN_KNOWN_PLAYERS:
                    skipped += 1
                    continue
                s1, s2 = m["score1"], m["score2"]
                margin = abs(s1 - s2) / (s1 + s2) if s1 is not None and s2 is not None and s1 + s2 > 0 else 0.0
                deltas = rate_match(l1, l2, m["winner_team_id"] == m["team1_id"], margin, tier_value(m["tournament_tier"]))
                team_of = {c[0]: m["team1_id"] for c in l1} | {c[0]: m["team2_id"] for c in l2}
                for pid, d in deltas.items():
                    rating, games = state[pid]
                    state[pid] = (rating + d, games + 1)
                    cur.execute(
                        "INSERT INTO player_rating_history (player_id, match_id, team_id, rating_after, delta, played_at)"
                        " VALUES (%s, %s, %s, %s, %s, %s)",
                        (pid, m["id"], team_of[pid], rating + d, d, m["scheduled_at"]),
                    )
                rated += 1
            for pid, (rating, games) in state.items():
                cur.execute(
                    "UPDATE player_rating SET rating = %s, matches_played = %s, updated_at = now() WHERE player_id = %s",
                    (rating, games, pid),
                )
        conn.commit()
    return {"seeded": seeded, "matches_rated": rated, "matches_skipped": skipped}
