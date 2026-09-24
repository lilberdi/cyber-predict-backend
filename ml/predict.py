from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from ml.config import MODEL_NAME, MODEL_VERSION
from ml.db import connect
from ml.features import snapshot_for_upcoming
from ml.load_history import finished_matches_frame
from ml.train import load_artifact, predict_proba


def _confidence(p: float) -> str:
    gap = abs(p - 0.5)
    if gap < 0.07:
        return "low"
    if gap < 0.15:
        return "medium"
    return "high"


def _explanation(team1: str, team2: str, p: float, feat: dict) -> str:
    fav = team1 if p >= 0.5 else team2
    return (
        f"{fav} оценивается выше ({p:.0%} для {team1}). "
        f"Разница Elo {feat['elo_diff']:+.0f}, форма (5 матчей) {feat['form5_diff']:+.2f}."
    )


def predict_upcoming() -> int:
    artifact = load_artifact()
    history = finished_matches_frame()
    written = 0
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id, t1.name AS team1, t2.name AS team2, m.scheduled_at
                FROM matches m
                JOIN teams t1 ON t1.id = m.team1_id
                JOIN teams t2 ON t2.id = m.team2_id
                WHERE m.status IN ('upcoming', 'running')
                ORDER BY m.scheduled_at NULLS LAST
                """
            )
            upcoming = cur.fetchall()
            now = datetime.now(timezone.utc)
            for row in upcoming:
                when = row["scheduled_at"] or now
                when_ts = pd.Timestamp(when)
                feat = snapshot_for_upcoming(history, row["team1"], row["team2"], when_ts)
                p1 = predict_proba(artifact, feat)
                p2 = 1.0 - p1
                top = [
                    {"name": "elo_diff", "value": round(feat["elo_diff"], 2), "impact": "favors_team1" if feat["elo_diff"] > 0 else "favors_team2"},
                    {"name": "form5_diff", "value": round(feat["form5_diff"], 3), "impact": "favors_team1" if feat["form5_diff"] > 0 else "favors_team2"},
                    {"name": "h2h_diff", "value": round(feat["h2h_diff"], 3), "impact": "favors_team1" if feat["h2h_diff"] > 0 else "favors_team2"},
                ]
                cur.execute(
                    """
                    INSERT INTO predictions (
                        match_id, model_name, model_version,
                        p_team1_win, p_team2_win, confidence, top_features, explanation
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (match_id) DO UPDATE
                        SET model_name = EXCLUDED.model_name,
                            model_version = EXCLUDED.model_version,
                            p_team1_win = EXCLUDED.p_team1_win,
                            p_team2_win = EXCLUDED.p_team2_win,
                            confidence = EXCLUDED.confidence,
                            top_features = EXCLUDED.top_features,
                            explanation = EXCLUDED.explanation,
                            created_at = now()
                    """,
                    (
                        row["id"],
                        MODEL_NAME,
                        MODEL_VERSION,
                        p1,
                        p2,
                        _confidence(p1),
                        json.dumps(top),
                        _explanation(row["team1"], row["team2"], p1, feat),
                    ),
                )
                written += 1
        conn.commit()
    return written
