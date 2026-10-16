from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import xgboost as xgb

from ml.config import MODEL_VERSION
from ml.db import connect
from ml.features import build_book, snapshot_for_upcoming
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


_FLIPPED = {"elo_diff", "form5_diff", "form10_diff", "h2h_diff", "exp_diff", "ewm_form_diff", "rest_diff", "margin_diff"}
MIN_HISTORY = 10  # matches of the less-known team needed for a full-strength forecast


def _calibrated_proba(artifact: dict, feat: dict) -> tuple[float, int]:
    """Slot-symmetric probability, shrunk toward 50% when a team has little history."""
    p_a = predict_proba(artifact, feat)
    flipped = {k: (-v if k in _FLIPPED else v) for k, v in feat.items()}
    p = (p_a + (1.0 - predict_proba(artifact, flipped))) / 2.0
    known = min(feat.get("games_team1", 0), feat.get("games_team2", 0))
    weight = min(1.0, known / MIN_HISTORY)
    return 0.5 + (p - 0.5) * weight, known


def _top_features(artifact: dict, feat: dict, limit: int = 5) -> list[dict]:
    """Per-match SHAP contributions (log-odds) for XGBoost; raw feature values otherwise."""
    cols = artifact["feature_columns"]
    clf = artifact["pipeline"].steps[-1][1]
    if hasattr(clf, "get_booster"):
        x = pd.DataFrame([{c: feat[c] for c in cols}])
        contrib = clf.get_booster().predict(xgb.DMatrix(x, feature_names=cols), pred_contribs=True)[0]
        ranked = sorted(zip(cols, contrib[:-1]), key=lambda kv: abs(kv[1]), reverse=True)[:limit]
        return [
            {
                "name": name,
                "value": round(float(feat[name]), 3),
                "impact": "favors_team1" if c > 0 else "favors_team2",
                "contribution": round(float(c), 3),
            }
            for name, c in ranked
        ]
    return [
        {"name": c, "value": round(float(feat[c]), 3), "impact": "favors_team1" if feat[c] > 0 else "favors_team2"}
        for c in cols
    ][:limit]


_INSERT_PREDICTION = """
    INSERT INTO predictions (
        match_id, model_name, model_version,
        p_team1_win, p_team2_win, confidence, top_features, explanation
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
"""
# Before the start a forecast is refreshed (created_at moves forward, still before the start).
_UPSERT_PREDICTION = _INSERT_PREDICTION + """
    ON CONFLICT (match_id) DO UPDATE
        SET model_name = EXCLUDED.model_name,
            model_version = EXCLUDED.model_version,
            p_team1_win = EXCLUDED.p_team1_win,
            p_team2_win = EXCLUDED.p_team2_win,
            confidence = EXCLUDED.confidence,
            top_features = EXCLUDED.top_features,
            explanation = EXCLUDED.explanation,
            created_at = now()
"""
# After the start the forecast is frozen: rewriting it would stamp it "after the match began"
# and drop it from the live accuracy check.
_UPSERT_PREDICTION_FROZEN = _INSERT_PREDICTION + " ON CONFLICT (match_id) DO NOTHING"


def is_started(scheduled_at, now) -> bool:
    return scheduled_at is not None and scheduled_at <= now


def predict_upcoming() -> int:
    artifact = load_artifact()
    history = finished_matches_frame()
    book = build_book(history)  # replayed once; all finished matches are in the past
    written = 0
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id, t1.name AS team1, t2.name AS team2, m.scheduled_at, m.best_of, m.tournament_tier
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
                feat = snapshot_for_upcoming(history, row["team1"], row["team2"], when_ts, row["best_of"] or 3, row["tournament_tier"], book=book)
                p1, known = _calibrated_proba(artifact, feat)
                p2 = 1.0 - p1
                top = _top_features(artifact, feat)
                note = ""
                if known < MIN_HISTORY:
                    note = f" Мало истории (у менее известной команды {known} матчей) — прогноз приближен к 50%."
                cur.execute(
                    _UPSERT_PREDICTION_FROZEN if is_started(row["scheduled_at"], now) else _UPSERT_PREDICTION,
                    (
                        row["id"],
                        artifact["model_name"],
                        MODEL_VERSION,
                        p1,
                        p2,
                        "low" if known < 3 else _confidence(p1),
                        json.dumps(top),
                        _explanation(row["team1"], row["team2"], p1, feat) + note,
                    ),
                )
                written += 1
        conn.commit()
    return written
