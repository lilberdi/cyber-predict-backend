from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.config import ARTIFACTS_DIR, MODEL_NAME, MODEL_VERSION, XGB_MODEL_NAME
from ml.db import connect
from ml.elo import EloBook
from ml.features import FEATURE_COLUMNS, XGB_FEATURE_COLUMNS, build_pre_match_features
from ml.load_history import finished_matches_frame


def _metrics(y_true, proba) -> dict:
    y_pred = (proba >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "log_loss": float(log_loss(y_true, proba, labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, proba)),
    }


XGB_GRID = [
    {"n_estimators": 40, "max_depth": 2, "learning_rate": 0.05, "min_child_weight": 10, "reg_lambda": 5.0},
    {"n_estimators": 80, "max_depth": 2, "learning_rate": 0.05, "min_child_weight": 8, "reg_lambda": 3.0},
    {"n_estimators": 120, "max_depth": 3, "learning_rate": 0.03, "min_child_weight": 5, "reg_lambda": 2.0},
]


def _select_xgb_params(train_df: pd.DataFrame) -> dict:
    """Pick hyper-parameters on the last 20% of the *training* part (test stays untouched)."""
    cut = int(len(train_df) * 0.8)
    fit, val = train_df.iloc[:cut], train_df.iloc[cut:]
    if val["team1_win"].nunique() < 2:
        return XGB_GRID[0]
    best, best_ll = XGB_GRID[0], float("inf")
    for params in XGB_GRID:
        m = XGBClassifier(eval_metric="logloss", random_state=42, subsample=0.8, colsample_bytree=0.8, **params)
        m.fit(fit[XGB_FEATURE_COLUMNS], fit["team1_win"])
        ll = log_loss(val["team1_win"], m.predict_proba(val[XGB_FEATURE_COLUMNS])[:, 1], labels=[0, 1])
        if ll < best_ll:
            best, best_ll = params, ll
    return best


def train() -> dict:
    history = finished_matches_frame()
    if len(history) < 40:
        raise RuntimeError("need at least 40 finished matches; run `python -m ml load-history`")

    feat = build_pre_match_features(history)
    split = int(len(feat) * 0.8)
    train_df, test_df = feat.iloc[:split], feat.iloc[split:]
    if test_df["team1_win"].nunique() < 2 or train_df["team1_win"].nunique() < 2:
        raise RuntimeError("chronological split has a single class; generate a larger sample")

    y_train, y_test = train_df["team1_win"], test_df["team1_win"]

    logreg = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=400))])
    logreg.fit(train_df[FEATURE_COLUMNS], y_train)
    lr_scores = _metrics(y_test.to_numpy(), logreg.predict_proba(test_df[FEATURE_COLUMNS])[:, 1])

    xgb_params = _select_xgb_params(train_df)
    xgb = Pipeline([("clf", XGBClassifier(eval_metric="logloss", random_state=42, subsample=0.8, colsample_bytree=0.8, **xgb_params))])
    xgb.fit(train_df[XGB_FEATURE_COLUMNS], y_train)
    xgb_scores = _metrics(y_test.to_numpy(), xgb.predict_proba(test_df[XGB_FEATURE_COLUMNS])[:, 1])
    gains = xgb.named_steps["clf"].get_booster().get_score(importance_type="gain")
    total_gain = sum(gains.values()) or 1.0
    importance = {c: round(gains.get(c, 0.0) / total_gain, 4) for c in XGB_FEATURE_COLUMNS}

    elo_favorite = (test_df["elo_diff"] > 0).astype(int)
    elo_acc = float(accuracy_score(y_test, elo_favorite))
    elo_proba = 1.0 / (1.0 + 10 ** (-test_df["elo_diff"].to_numpy() / 400.0))
    elo_scores = _metrics(y_test.to_numpy(), elo_proba)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    lr_path = ARTIFACTS_DIR / f"{MODEL_NAME}.joblib"
    xgb_path = ARTIFACTS_DIR / f"{XGB_MODEL_NAME}.joblib"
    joblib.dump(
        {"pipeline": logreg, "feature_columns": FEATURE_COLUMNS, "model_name": MODEL_NAME, "model_version": MODEL_VERSION},
        lr_path,
    )
    joblib.dump(
        {"pipeline": xgb, "feature_columns": XGB_FEATURE_COLUMNS, "model_name": XGB_MODEL_NAME, "model_version": MODEL_VERSION},
        xgb_path,
    )

    comparison = {
        "elo_only": {**elo_scores, "label": "Elo (правило фаворита)"},
        MODEL_NAME: {**lr_scores, "label": "Logistic regression"},
        XGB_MODEL_NAME: {**xgb_scores, "label": "XGBoost"},
    }
    base_extra = {
        "split": "chronological_80_20",
        "leakage_guard": "features use only matches before played_at",
        "comparison": comparison,
        "active_model": XGB_MODEL_NAME,
    }
    common = {"model_version": MODEL_VERSION, "n_train": int(len(train_df)), "n_test": int(len(test_df)), "elo_favorite_accuracy": elo_acc}
    lr_report = {
        "model_name": MODEL_NAME, **common, **lr_scores,
        "artifact": str(lr_path), "extra": {**base_extra, "features": FEATURE_COLUMNS},
    }
    xgb_report = {
        "model_name": XGB_MODEL_NAME, **common, **xgb_scores,
        "artifact": str(xgb_path),
        "extra": {**base_extra, "features": XGB_FEATURE_COLUMNS, "feature_importance": importance, "xgb_params": xgb_params},
    }
    (ARTIFACTS_DIR / "metrics.json").write_text(json.dumps(xgb_report, indent=2), encoding="utf-8")

    _persist_elo(history)
    # XGBoost goes last so GET /model/metrics (latest row) reports the production model.
    _persist_metrics(lr_report)
    _persist_metrics(xgb_report)
    return xgb_report


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
    """Production model is XGBoost; fall back to the logreg baseline if it is missing."""
    if path is None:
        path = ARTIFACTS_DIR / f"{XGB_MODEL_NAME}.joblib"
        if not path.exists():
            path = ARTIFACTS_DIR / f"{MODEL_NAME}.joblib"
    if not path.exists():
        raise FileNotFoundError(f"missing model artifact {path}; run `python -m ml train`")
    return joblib.load(path)


def predict_proba(artifact: dict, features: dict) -> float:
    cols = artifact["feature_columns"]
    x = pd.DataFrame([{c: features[c] for c in cols}])
    return float(artifact["pipeline"].predict_proba(x)[0, 1])
