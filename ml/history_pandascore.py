"""Real finished CS2 matches from the official PandaScore API (no HLTV scraping).

`python -m ml ingest-past` backfills history (default: ~10k newest matches, enough
for a student project and light on the laptop); the worker calls it daily with a
short window so new results (and results of matches we predicted) keep flowing in.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ml.config import PANDASCORE_BASE_URL, PANDASCORE_TOKEN
from ml.db import connect
from ml.pandascore import CS2_TITLE_ID, PandaScoreError

DEFAULT_MAX_PAGES = 100  # 100 pages x 100 matches


def _fetch_page(client: httpx.Client, page: int) -> list[dict[str, Any]]:
    params = {
        "per_page": 100,
        "page": page,
        "sort": "-begin_at",
        "filter[videogame_title]": CS2_TITLE_ID,
        "filter[status]": "finished",
    }
    url = f"{PANDASCORE_BASE_URL}/csgo/matches/past"
    resp = client.get(url, params=params)
    if resp.status_code == 429:  # hourly rate limit: wait and retry once
        time.sleep(30)
        resp = client.get(url, params=params)
    if resp.status_code >= 400:
        raise PandaScoreError(f"pandascore {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return data if isinstance(data, list) else []


def normalize_finished(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only clean 2-team results with a known winner and start time."""
    if raw.get("forfeit") or raw.get("draw") or not raw.get("begin_at") or not raw.get("winner_id"):
        return None
    teams = [(o.get("opponent") or {}) for o in (raw.get("opponents") or [])]
    if len(teams) != 2 or not all(t.get("id") and t.get("name") for t in teams):
        return None
    ids = [t["id"] for t in teams]
    if raw["winner_id"] not in ids or ids[0] == ids[1]:
        return None
    scores = {r.get("team_id"): r.get("score") for r in (raw.get("results") or [])}
    tour = raw.get("tournament") or {}
    return {
        "external_id": f"ps-{raw['id']}",
        "begin_at": raw["begin_at"],
        "best_of": raw.get("number_of_games"),
        "tournament": tour.get("name") or (raw.get("league") or {}).get("name"),
        "tier": (tour.get("tier") or "").lower() or None,
        "teams": teams,
        "score1": scores.get(ids[0]),
        "score2": scores.get(ids[1]),
        "winner_id": raw["winner_id"],
    }


class _Teams:
    """Resolves PandaScore teams to DB ids; names stay unique even if PandaScore reuses them."""

    def __init__(self, cur):
        self.cur, self.cache = cur, {}

    def get(self, team: dict[str, Any]) -> int:
        ext = f"ps-team-{team['id']}"
        if ext in self.cache:
            return self.cache[ext]
        cur = self.cur
        cur.execute("SELECT id FROM teams WHERE external_id = %s", (ext,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT id, external_id FROM teams WHERE lower(name) = lower(%s)", (team["name"],))
            same = cur.fetchone()
            name = team["name"]
            if same and same["external_id"] is None:
                cur.execute(
                    "UPDATE teams SET external_id = %s, slug = %s, image_url = %s WHERE id = %s",
                    (ext, team.get("slug"), team.get("image_url"), same["id"]),
                )
                row = same
            else:
                if same:
                    name = f"{name} ({team['id']})"
                cur.execute(
                    "INSERT INTO teams (external_id, name, slug, image_url) VALUES (%s, %s, %s, %s) RETURNING id",
                    (ext, name, team.get("slug"), team.get("image_url")),
                )
                row = cur.fetchone()
        self.cache[ext] = int(row["id"])
        return self.cache[ext]


def ingest(max_pages: int = DEFAULT_MAX_PAGES, since: datetime | None = None) -> dict:
    """Fetch pages (newest first) until `since` or `max_pages`; upsert as finished matches."""
    if not PANDASCORE_TOKEN:
        raise PandaScoreError("PANDASCORE_TOKEN is empty; real history needs the token")
    headers = {"Authorization": f"Bearer {PANDASCORE_TOKEN}", "Accept": "application/json"}
    seen = kept = 0
    with httpx.Client(timeout=30.0, headers=headers) as client, connect() as conn:
        with conn.cursor() as cur:
            teams = _Teams(cur)
            for page in range(1, max_pages + 1):
                batch = _fetch_page(client, page)
                if not batch:
                    break
                seen += len(batch)
                for raw in batch:
                    m = normalize_finished(raw)
                    if not m:
                        continue
                    t1, t2 = (teams.get(t) for t in m["teams"])
                    winner = t1 if m["winner_id"] == m["teams"][0]["id"] else t2
                    cur.execute(
                        """
                        INSERT INTO matches (external_id, source, team1_id, team2_id, tournament,
                            tournament_tier, best_of, scheduled_at, status, score1, score2, winner_team_id)
                        VALUES (%s, 'pandascore', %s, %s, %s, %s, %s, %s, 'finished', %s, %s, %s)
                        ON CONFLICT (external_id) DO UPDATE
                            SET status = 'finished', score1 = EXCLUDED.score1, score2 = EXCLUDED.score2,
                                winner_team_id = EXCLUDED.winner_team_id, updated_at = now()
                        """,
                        (m["external_id"], t1, t2, m["tournament"], m["tier"], m["best_of"],
                         m["begin_at"], m["score1"], m["score2"], winner),
                    )
                    kept += 1
                conn.commit()
                oldest = batch[-1].get("begin_at")
                if since and oldest and datetime.fromisoformat(oldest.replace("Z", "+00:00")) < since:
                    break
    return {"pages_seen": seen, "stored": kept}


def ingest_recent(days: int = 3) -> dict:
    return ingest(max_pages=20, since=datetime.now(timezone.utc) - timedelta(days=days))
