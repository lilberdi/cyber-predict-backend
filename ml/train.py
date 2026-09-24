from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.config import ARTIFACTS_DIR, MODEL_NAME, MODEL_VERSION
from ml.db import connect
from ml.elo import EloBook
from ml.features import FEATURE_COLUMNS, build_pre_match_features
from ml.load_history import finished_matches_frame


def _metrics(y_true, proba) -> dict:
    y_pred = (proba >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "log_loss": float(log_loss(y_true, proba, labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, proba)),
    }


def train() -> dict:
    history = finished_matches_frame()
    if len(history) < 40:
        raise RuntimeError("need at least 40 finished matches; run `python -m ml load-history`")

    feat = build_pre_match_features(history)
    split = int(len(feat) * 0.8)
    train_df, test_df = feat.iloc[:split], feat.iloc[split:]
    if test_df["team1_win"].nunique() < 2 or train_df["team1_win"].nunique() < 2:
        raise RuntimeError("chronological split has a single class; generate a larger sample")

    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=400)),
        ]
    )
    pipe.fit(train_df[FEATURE_COLUMNS], train_df["team1_win"])
    proba = pipe.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
    model_scores = _metrics(test_df["team1_win"].to_numpy(), proba)

    elo_favorite = (test_df["elo_diff"] > 0).astype(int)
    elo_acc = float(accuracy_score(test_df["team1_win"], elo_favorite))

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = ARTIFACTS_DIR / f"{MODEL_NAME}.joblib"
    joblib.dump(
        {
            "pipeline": pipe,
            "feature_columns": FEATURE_COLUMNS,
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
        },
        model_path,
    )

    extra = {
        "features": FEATURE_COLUMNS,
        "split": "chronological_80_20",
        "leakage_guard": "features use only matches before played_at",
    }
    report = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "n_train": int(len(train_df)),
        "n_test": int(len(test_df)),
        **model_scores,
        "elo_favorite_accuracy": elo_acc,
        "artifact": str(model_path),
        "extra": extra,
    }
    (ARTIFACTS_DIR / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    _persist_elo(history)
    _persist_metrics(report)
    return report


def _persist_elo(history: pd.DataFrame) -> None:
    book = EloBook.fresh()
    for row in history.sort_values("played_at").itertuples(index=False):
        book.apply(row.team1, row.team2, row.winner == row.team1)
    with connect() as conn:
        with conn.cursor() as cur:
            for name, rating in book.ratings.items():
                cur.execute(
                    """
                    INSERT INTO team_elo (team_id, rating, matches_played, updated_at)
                    SELECT id, %s, %s, now() FROM teams WHERE lower(name) = lower(%s)
                    ON CONFLICT (team_id) DO UPDATE
                        SET rating = EXCLUDED.rating,
                            matches_played = EXCLUDED.matches_played,
                            updated_at = now()
                    """,
                    (float(rating), int(book.played.get(name, 0)), name),
                )
        conn.commit()


def _persist_metrics(report: dict) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_metrics (
                    model_name, model_version, n_train, n_test,
                    accuracy, log_loss, brier, elo_favorite_accuracy, extra
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    report["model_name"],
                    report["model_version"],
                    report["n_train"],
                    report["n_test"],
                    report["accuracy"],
                    report["log_loss"],
                    report["brier"],
                    report["elo_favorite_accuracy"],
                    json.dumps(report["extra"]),
                ),
            )
        conn.commit()


def load_artifact(path: Path | None = None):
    model_path = path or (ARTIFACTS_DIR / f"{MODEL_NAME}.joblib")
    if not model_path.exists():
        raise FileNotFoundError(f"missing model artifact {model_path}; run `python -m ml train`")
    return joblib.load(model_path)


def predict_proba(artifact: dict, features: dict) -> float:
    cols = artifact["feature_columns"]
    x = pd.DataFrame([{c: features[c] for c in cols}])
    return float(artifact["pipeline"].predict_proba(x)[0, 1])
