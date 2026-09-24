from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ml.config import FIXTURES_PATH
from ml.db import connect, upsert_team
from ml.pandascore import PandaScoreError, fetch_upcoming, normalize_match


def _load_fixtures() -> list[dict[str, Any]]:
    payload = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    matches = payload.get("matches", payload) if isinstance(payload, dict) else payload
    out = []
    for raw in matches:
        out.append(
            {
                "external_id": raw["external_id"],
                "team1": raw["team1"],
                "team2": raw["team2"],
                "team1_external_id": raw.get("team1_external_id"),
                "team2_external_id": raw.get("team2_external_id"),
                "team1_image": raw.get("team1_image"),
                "team2_image": raw.get("team2_image"),
                "team1_slug": raw.get("team1_slug"),
                "team2_slug": raw.get("team2_slug"),
                "scheduled_at": raw.get("scheduled_at"),
                "best_of": raw.get("best_of", 3),
                "tournament": raw.get("tournament"),
                "status": raw.get("status", "upcoming"),
                "source": "fixture",
            }
        )
    return out


def collect_upcoming() -> tuple[list[dict[str, Any]], str]:
    try:
        raw = fetch_upcoming()
        items = [m for m in (normalize_match(x) for x in raw) if m]
        if items:
            return items, "pandascore"
    except PandaScoreError:
        pass
    return _load_fixtures(), "fixture"


def upsert_upcoming(items: list[dict[str, Any]]) -> int:
    count = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for item in items:
                t1 = upsert_team(
                    cur,
                    item["team1"],
                    external_id=item.get("team1_external_id"),
                    slug=item.get("team1_slug"),
                    image_url=item.get("team1_image"),
                )
                t2 = upsert_team(
                    cur,
                    item["team2"],
                    external_id=item.get("team2_external_id"),
                    slug=item.get("team2_slug"),
                    image_url=item.get("team2_image"),
                )
                when = item.get("scheduled_at")
                if when:
                    when = pd.Timestamp(when).to_pydatetime()
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                else:
                    when = datetime.now(timezone.utc)
                cur.execute(
                    """
                    INSERT INTO matches (
                        external_id, source, team1_id, team2_id, tournament,
                        best_of, scheduled_at, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (external_id) DO UPDATE
                        SET scheduled_at = EXCLUDED.scheduled_at,
                            status = EXCLUDED.status,
                            tournament = COALESCE(EXCLUDED.tournament, matches.tournament),
                            updated_at = now()
                    """,
                    (
                        item["external_id"],
                        item["source"],
                        t1,
                        t2,
                        item.get("tournament"),
                        item.get("best_of") or 3,
                        when,
                        item.get("status") or "upcoming",
                    ),
                )
                count += 1
        conn.commit()
    return count


def sync() -> dict:
    items, source = collect_upcoming()
    return {"source": source, "upserted": upsert_upcoming(items)}
