"""Live comparison: stored pre-match XGBoost predictions vs the Elo-favorite rule on the same matches.

The XGBoost number is what was really shown to users before the match. Elo is replayed from
history with the same leakage guard as training: a match only sees games played before it.
Both are scored on exactly the matches counted by GET /api/v1/model/live-accuracy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.db import connect
from ml.features import build_pre_match_features
from ml.load_history import finished_matches_frame
from ml.train import _bootstrap_ci

EPS = 1e-6


def _scores(y: np.ndarray, p: np.ndarray) -> dict:
    p = np.clip(p, EPS, 1 - EPS)
    return {
        "accuracy": round(float(((p >= 0.5) == (y == 1)).mean()), 4),
        "log_loss": round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4),
        "brier": round(float(((p - y) ** 2).mean()), 4),
    }


def _live_predictions() -> pd.DataFrame:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.external_id AS match_id, m.tournament_tier AS tier, p.model_name,
                       p.p_team1_win AS p_model, (m.winner_team_id = m.team1_id)::int AS team1_win
                FROM matches m JOIN predictions p ON p.match_id = m.id
                WHERE m.status = 'finished' AND m.winner_team_id IS NOT NULL AND m.voided_reason IS NULL
                  AND p.created_at <= m.scheduled_at AND p.p_team1_win <> 0.5
                """
            )
            return pd.DataFrame(cur.fetchall())


def compare(min_games: int = 10) -> dict:
    live = _live_predictions()
    if live.empty:
        return {"evaluated": 0, "note": "no scored live predictions yet"}
    live = live[live["model_name"] == "elo_xgboost"]

    feat = build_pre_match_features(finished_matches_frame())
    feat = feat[["match_id", "elo_diff", "games_team1", "games_team2"]]
    df = live.merge(feat, on="match_id", how="inner")
    dropped = len(live) - len(df)
    if df.empty:
        return {"evaluated": 0, "note": "live matches not found in history"}

    y = df["team1_win"].to_numpy()
    p_xgb = df["p_model"].to_numpy(dtype=float)
    p_elo = 1.0 / (1.0 + 10 ** (-df["elo_diff"].to_numpy(dtype=float) / 400.0))

    # an exact Elo tie has no favorite: count it as half a hit so the rule is not helped or hurt
    elo_hit = np.where(p_elo == 0.5, 0.5, ((p_elo >= 0.5) == (y == 1)).astype(float))
    xgb_hit = ((p_xgb >= 0.5) == (y == 1)).astype(float)

    known = (np.minimum(df["games_team1"], df["games_team2"]) >= min_games).to_numpy()
    by_tier = {}
    for tier, sub in df.groupby(df["tier"].fillna("unknown").str.lower()):
        idx = sub.index.to_numpy()
        by_tier[tier] = {
            "n": len(idx),
            "xgboost_accuracy": round(float(xgb_hit[idx].mean()), 4),
            "elo_accuracy": round(float(elo_hit[idx].mean()), 4),
        }

    return {
        "evaluated": len(df),
        "not_in_history": dropped,
        "xgboost": _scores(y, p_xgb),
        "elo": _scores(y, p_elo),
        "accuracy_diff_xgb_minus_elo": _bootstrap_ci(xgb_hit, elo_hit),
        "known_teams_only": {
            "min_games": min_games,
            "n": int(known.sum()),
            "xgboost": _scores(y[known], p_xgb[known]) if known.any() else None,
            "elo": _scores(y[known], p_elo[known]) if known.any() else None,
        },
        "by_tier": by_tier,
        "note": "Elo is replayed from history using only earlier matches; XGBoost is the stored pre-match prediction.",
    }
