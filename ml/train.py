from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.config import ARTIFACTS_DIR, MODEL_NAME, MODEL_VERSION, XGB_MODEL_NAME
from ml.db import connect
from ml.features import EXTRA_FEATURES, FEATURE_COLUMNS, XGB_FEATURE_COLUMNS, build_book, build_pre_match_features
from ml.load_history import finished_matches_frame

MIN_KNOWN_GAMES = 10  # a team counts as "known" after this many matches in history
WALK_FORWARD_FOLDS = 5
BOOTSTRAP_ROUNDS = 1000

XGB_GRID = [
    {"n_estimators": 40, "max_depth": 2, "learning_rate": 0.05, "min_child_weight": 10, "reg_lambda": 5.0},
    {"n_estimators": 80, "max_depth": 2, "learning_rate": 0.05, "min_child_weight": 8, "reg_lambda": 3.0},
    {"n_estimators": 120, "max_depth": 3, "learning_rate": 0.03, "min_child_weight": 5, "reg_lambda": 2.0},
    {"n_estimators": 200, "max_depth": 3, "learning_rate": 0.03, "min_child_weight": 20, "reg_lambda": 5.0},
]


# ---------- metrics ----------

def _metrics(y_true, proba) -> dict:
    y_pred = (np.asarray(proba) >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "log_loss": float(log_loss(y_true, proba, labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, proba)),
    }


def _ece(y_true, proba, bins: int = 10) -> tuple[float, list[dict]]:
    """Expected calibration error plus reliability bins for a chart."""
    y, p = np.asarray(y_true), np.asarray(proba)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece, table = 0.0, []
    for b in range(bins):
        mask = idx == b
        if not mask.any():
            continue
        conf, freq = float(p[mask].mean()), float(y[mask].mean())
        ece += mask.mean() * abs(conf - freq)
        table.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(mask.sum()), "predicted": round(conf, 3), "actual": round(freq, 3)})
    return float(ece), table


def _bootstrap_ci(correct_a: np.ndarray, correct_b: np.ndarray | None = None, seed: int = 7) -> dict:
    """95% CI for accuracy of A (or for accuracy(A) - accuracy(B), paired)."""
    rng = np.random.default_rng(seed)
    n = len(correct_a)
    stat = correct_a.astype(float) if correct_b is None else correct_a.astype(float) - correct_b.astype(float)
    draws = [stat[rng.integers(0, n, n)].mean() for _ in range(BOOTSTRAP_ROUNDS)]
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"mean": float(stat.mean()), "ci95": [float(lo), float(hi)]}


def _elo_proba(df: pd.DataFrame) -> np.ndarray:
    return 1.0 / (1.0 + 10 ** (-df["elo_diff"].to_numpy() / 400.0))


# ---------- models ----------

def _make_logreg() -> Pipeline:
    return Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=400))])


def _make_xgb(params: dict) -> Pipeline:
    clf = XGBClassifier(eval_metric="logloss", random_state=42, subsample=0.8, colsample_bytree=0.8, n_jobs=2, **params)
    return Pipeline([("clf", clf)])


def _select_xgb_params(train_df: pd.DataFrame) -> dict:
    """Pick hyper-parameters on the last 20% of the *training* part (test stays untouched)."""
    cut = int(len(train_df) * 0.8)
    fit, val = train_df.iloc[:cut], train_df.iloc[cut:]
    if val["team1_win"].nunique() < 2:
        return XGB_GRID[0]
    best, best_ll = XGB_GRID[0], float("inf")
    for params in XGB_GRID:
        m = _make_xgb(params).fit(fit[XGB_FEATURE_COLUMNS], fit["team1_win"])
        ll = log_loss(val["team1_win"], m.predict_proba(val[XGB_FEATURE_COLUMNS])[:, 1], labels=[0, 1])
        if ll < best_ll:
            best, best_ll = params, ll
    return best


def _logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p)).reshape(-1, 1)


def _fit_calibrator(kind: str, proba, y):
    if kind == "platt":
        return ("platt", LogisticRegression().fit(_logit(proba), y))
    return ("isotonic", IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99).fit(proba, y))


def _choose_calibrator(proba, y) -> str:
    """Fit on the first half of the calibration slice, score log-loss on the second; raw wins ties."""
    half = len(proba) // 2
    if half < 50 or len(set(y[:half])) < 2:
        return "raw"
    best, best_ll = "raw", log_loss(y[half:], np.clip(proba[half:], 1e-4, 1 - 1e-4), labels=[0, 1])
    for kind in ("platt", "isotonic"):
        p = np.clip(apply_calibrator(_fit_calibrator(kind, proba[:half], y[:half]), proba[half:]), 1e-4, 1 - 1e-4)
        ll = log_loss(y[half:], p, labels=[0, 1])
        if ll < best_ll - 1e-4:
            best, best_ll = kind, ll
    return best


def apply_calibrator(calibrator, proba):
    if calibrator is None:
        return proba
    kind, model = calibrator
    if kind == "platt":
        return model.predict_proba(_logit(proba))[:, 1]
    return model.predict(np.asarray(proba, dtype=float))


# ---------- evaluation ----------

def walk_forward(feat: pd.DataFrame, params: dict, columns: list[str], folds: int = WALK_FORWARD_FOLDS) -> dict:
    """Expanding-window evaluation: train on the past, test on the next time block."""
    chunks = np.array_split(np.arange(len(feat)), folds + 1)
    rows: dict[str, list[dict]] = {"elo_only": [], "elo_logreg": [], "elo_xgboost": []}
    for k in range(1, folds + 1):
        tr = feat.iloc[np.concatenate(chunks[:k])]
        te = feat.iloc[chunks[k]]
        if tr["team1_win"].nunique() < 2 or te["team1_win"].nunique() < 2:
            continue
        y = te["team1_win"].to_numpy()
        rows["elo_only"].append(_metrics(y, _elo_proba(te)))
        lr = _make_logreg().fit(tr[FEATURE_COLUMNS], tr["team1_win"])
        rows["elo_logreg"].append(_metrics(y, lr.predict_proba(te[FEATURE_COLUMNS])[:, 1]))
        xg = _make_xgb(params).fit(tr[columns], tr["team1_win"])
        rows["elo_xgboost"].append(_metrics(y, xg.predict_proba(te[columns])[:, 1]))
    return {
        name: {
            key: {"mean": float(np.mean([r[key] for r in res])), "std": float(np.std([r[key] for r in res]))}
            for key in ("accuracy", "log_loss", "brier")
        }
        for name, res in rows.items() if res
    }


def ablation(feat: pd.DataFrame, params: dict) -> dict:
    """Walk-forward scores with each extra feature removed. A positive gain means the feature helps."""
    base = walk_forward(feat, params, XGB_FEATURE_COLUMNS)["elo_xgboost"]
    out = {}
    for name in EXTRA_FEATURES:
        cols = [c for c in XGB_FEATURE_COLUMNS if c != name]
        res = walk_forward(feat, params, cols)["elo_xgboost"]
        out[name] = {
            "log_loss_without": round(res["log_loss"]["mean"], 4),
            "log_loss_gain": round(res["log_loss"]["mean"] - base["log_loss"]["mean"], 4),
            "accuracy_without": round(res["accuracy"]["mean"], 4),
            "accuracy_gain": round(base["accuracy"]["mean"] - res["accuracy"]["mean"], 4),
        }
    return out


def train() -> dict:
    history = finished_matches_frame()
    if len(history) < 40:
        raise RuntimeError("need at least 40 finished matches; run `python -m ml ingest-past`")

    feat = build_pre_match_features(history)
    n = len(feat)
    split = int(n * 0.8)
    train_df, test_df = feat.iloc[:split], feat.iloc[split:]
    if test_df["team1_win"].nunique() < 2 or train_df["team1_win"].nunique() < 2:
        raise RuntimeError("chronological split has a single class; load more history")
    y_test = test_df["team1_win"].to_numpy()

    xgb_params = _select_xgb_params(train_df)

    # Base XGBoost learns on the first 85% of train; the last 15% calibrates probabilities.
    cal_cut = int(len(train_df) * 0.85)
    fit_df, cal_df = train_df.iloc[:cal_cut], train_df.iloc[cal_cut:]
    logreg = _make_logreg().fit(train_df[FEATURE_COLUMNS], train_df["team1_win"])
    xgb = _make_xgb(xgb_params).fit(fit_df[XGB_FEATURE_COLUMNS], fit_df["team1_win"])

    raw_cal = xgb.predict_proba(cal_df[XGB_FEATURE_COLUMNS])[:, 1]
    y_cal = cal_df["team1_win"].to_numpy()
    calibrators = {"raw": None, "platt": _fit_calibrator("platt", raw_cal, y_cal), "isotonic": _fit_calibrator("isotonic", raw_cal, y_cal)}
    chosen = _choose_calibrator(raw_cal, y_cal)  # decided on calibration data only, never on test

    raw_test = xgb.predict_proba(test_df[XGB_FEATURE_COLUMNS])[:, 1]
    calibration = {}
    for name, cal in calibrators.items():
        p = apply_calibrator(cal, raw_test)
        calibration[name] = {**_metrics(y_test, p), "ece": round(_ece(y_test, p)[0], 4)}
    xgb_proba = apply_calibrator(calibrators[chosen], raw_test)
    ece, reliability = _ece(y_test, xgb_proba)

    lr_proba = logreg.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
    elo_proba = _elo_proba(test_df)
    xgb_scores, lr_scores, elo_scores = _metrics(y_test, xgb_proba), _metrics(y_test, lr_proba), _metrics(y_test, elo_proba)

    known = (np.minimum(test_df["games_team1"], test_df["games_team2"]) >= MIN_KNOWN_GAMES).to_numpy()
    known_scores = {
        "n": int(known.sum()),
        "elo_only": _metrics(y_test[known], elo_proba[known]) if known.sum() > 20 else None,
        "elo_xgboost": _metrics(y_test[known], xgb_proba[known]) if known.sum() > 20 else None,
    }

    def correct(p):
        return (p >= 0.5).astype(int) == y_test

    significance = {
        "xgboost_accuracy": _bootstrap_ci(correct(xgb_proba)),
        "elo_accuracy": _bootstrap_ci(correct(elo_proba)),
        "xgboost_minus_elo": _bootstrap_ci(correct(xgb_proba), correct(elo_proba)),
        "xgboost_minus_logreg": _bootstrap_ci(correct(xgb_proba), correct(lr_proba)),
    }

    cv = walk_forward(feat, xgb_params, XGB_FEATURE_COLUMNS)
    ablate = ablation(feat, xgb_params)

    gains = xgb.named_steps["clf"].get_booster().get_score(importance_type="gain")
    total_gain = sum(gains.values()) or 1.0
    importance = {c: round(gains.get(c, 0.0) / total_gain, 4) for c in XGB_FEATURE_COLUMNS}

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    lr_path = ARTIFACTS_DIR / f"{MODEL_NAME}.joblib"
    xgb_path = ARTIFACTS_DIR / f"{XGB_MODEL_NAME}.joblib"
    joblib.dump({"pipeline": logreg, "feature_columns": FEATURE_COLUMNS, "model_name": MODEL_NAME, "model_version": MODEL_VERSION, "calibrator": None}, lr_path)
    joblib.dump(
        {"pipeline": xgb, "feature_columns": XGB_FEATURE_COLUMNS, "model_name": XGB_MODEL_NAME, "model_version": MODEL_VERSION, "calibrator": calibrators[chosen]},
        xgb_path,
    )

    comparison = {
        "elo_only": {**elo_scores, "label": "Elo (правило фаворита)"},
        MODEL_NAME: {**lr_scores, "label": "Logistic regression"},
        XGB_MODEL_NAME: {**xgb_scores, "label": "XGBoost"},
    }
    real = bool(history["match_id"].astype(str).str.startswith("ps-").any())
    base_extra = {
        "split": "chronological_80_20",
        "leakage_guard": "features use only matches before played_at",
        "data": {
            "source": "pandascore" if real else "synthetic",
            "n_matches": int(n),
            "n_teams": int(pd.concat([feat["team1"], feat["team2"]]).nunique()),
            "from": str(feat["played_at"].min()),
            "to": str(feat["played_at"].max()),
        },
        "comparison": comparison,
        "active_model": XGB_MODEL_NAME,
        "walk_forward": {"folds": WALK_FORWARD_FOLDS, "results": cv},
        "significance": significance,
        "known_teams_only": {"min_games": MIN_KNOWN_GAMES, **known_scores},
    }
    common = {"model_version": MODEL_VERSION, "n_train": int(len(train_df)), "n_test": int(len(test_df)), "elo_favorite_accuracy": elo_scores["accuracy"]}
    lr_report = {"model_name": MODEL_NAME, **common, **lr_scores, "artifact": str(lr_path), "extra": {**base_extra, "features": FEATURE_COLUMNS}}
    xgb_report = {
        "model_name": XGB_MODEL_NAME, **common, **xgb_scores, "artifact": str(xgb_path),
        "extra": {
            **base_extra,
            "features": XGB_FEATURE_COLUMNS,
            "feature_importance": importance,
            "xgb_params": xgb_params,
            "ablation": ablate,
            "calibration": {"chosen": chosen, "ece": round(ece, 4), "compare": calibration, "reliability": reliability},
        },
    }
    (ARTIFACTS_DIR / "metrics.json").write_text(json.dumps(xgb_report, indent=2, ensure_ascii=False), encoding="utf-8")

    _persist_elo(history)
    # XGBoost goes last so GET /model/metrics (latest row) reports the production model.
    _persist_metrics(lr_report)
    _persist_metrics(xgb_report)
    return xgb_report


def _persist_elo(history: pd.DataFrame) -> None:
    book = build_book(history)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM team_elo")
            for name, rating in book.elo.ratings.items():
                cur.execute(
                    """
                    INSERT INTO team_elo (team_id, rating, matches_played, updated_at)
                    SELECT id, %s, %s, now() FROM teams WHERE lower(name) = lower(%s)
                    ON CONFLICT (team_id) DO UPDATE
                        SET rating = EXCLUDED.rating,
                            matches_played = EXCLUDED.matches_played,
                            updated_at = now()
                    """,
                    (float(rating), int(book.elo.played.get(name, 0)), name),
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
                    report["model_name"], report["model_version"], report["n_train"], report["n_test"],
                    report["accuracy"], report["log_loss"], report["brier"], report["elo_favorite_accuracy"],
                    json.dumps(report["extra"], ensure_ascii=False),
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
    p = artifact["pipeline"].predict_proba(x)[:, 1]
    return float(apply_calibrator(artifact.get("calibrator"), p)[0])
