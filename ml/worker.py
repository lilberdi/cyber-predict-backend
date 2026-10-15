"""Keeps XGBoost predictions fresh for upcoming matches synced by the Go API."""

from __future__ import annotations

import os
import time

from ml.config import ARTIFACTS_DIR, XGB_MODEL_NAME
from ml.load_history import finished_matches_frame, load_csv
from ml.predict import predict_upcoming
from ml.train import train

INTERVAL_SECONDS = int(os.getenv("PREDICT_INTERVAL_SECONDS", "600"))


def _bootstrap() -> None:
    if len(finished_matches_frame()) < 40:
        print(f"history: loaded {load_csv()} matches", flush=True)
    if not (ARTIFACTS_DIR / f"{XGB_MODEL_NAME}.joblib").exists():
        report = train()
        print(f"trained {report['model_name']} acc={report['accuracy']:.3f}", flush=True)


def run() -> None:
    while True:
        try:
            _bootstrap()
            print(f"predicted {predict_upcoming()} upcoming matches", flush=True)
        except Exception as exc:  # DB or API may not be ready yet
            print(f"worker: {exc}", flush=True)
        time.sleep(INTERVAL_SECONDS)
