"""Official PandaScore client. No HLTV scraping."""

from __future__ import annotations

from typing import Any

import httpx

from ml.config import PANDASCORE_BASE_URL, PANDASCORE_TOKEN

CS2_TITLE_ID = 13


class PandaScoreError(RuntimeError):
    pass


def fetch_upcoming(limit: int = 50) -> list[dict[str, Any]]:
    if not PANDASCORE_TOKEN:
        raise PandaScoreError("PANDASCORE_TOKEN is empty; use fixtures or set the token")

    url = f"{PANDASCORE_BASE_URL}/csgo/matches/upcoming"
    headers = {
        "Authorization": f"Bearer {PANDASCORE_TOKEN}",
        "Accept": "application/json",
    }
    params = {
        "filter[videogame_title]": CS2_TITLE_ID,
        "per_page": min(limit, 100),
        "sort": "begin_at",
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(url, headers=headers, params=params)
        if resp.status_code >= 400:
            raise PandaScoreError(f"pandascore {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
    if not isinstance(data, list):
        raise PandaScoreError("unexpected pandascore payload")
    return data


def normalize_match(raw: dict[str, Any]) -> dict[str, Any] | None:
    opponents = raw.get("opponents") or []
    teams = [item.get("opponent") or {} for item in opponents if item.get("type") == "Team" or item.get("opponent")]
    if len(teams) < 2:
        return None
    t1, t2 = teams[0], teams[1]
    if not t1.get("name") or not t2.get("name"):
        return None
    tournament = (raw.get("tournament") or {}).get("name") or (raw.get("league") or {}).get("name")
    return {
        "external_id": f"ps-{raw.get('id')}",
        "team1": t1.get("name"),
        "team2": t2.get("name"),
        "team1_external_id": f"ps-team-{t1.get('id')}" if t1.get("id") else None,
        "team2_external_id": f"ps-team-{t2.get('id')}" if t2.get("id") else None,
        "team1_image": t1.get("image_url"),
        "team2_image": t2.get("image_url"),
        "team1_slug": t1.get("slug"),
        "team2_slug": t2.get("slug"),
        "scheduled_at": raw.get("begin_at") or raw.get("scheduled_at"),
        "best_of": raw.get("number_of_games"),
        "tournament": tournament,
        "status": "running" if raw.get("status") == "running" else "upcoming",
        "source": "pandascore",
    }
