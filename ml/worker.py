"""Keeps real history, the model and XGBoost predictions fresh.

Every cycle: refresh predictions for new upcoming matches. Every few hours: pull
newly finished matches (this also closes the loop for matches we predicted).
Once a day: retrain.
"""

from __future__ import annotations

import os
import time

from ml.config import ARTIFACTS_DIR, PANDASCORE_TOKEN, XGB_MODEL_NAME
from ml.history_pandascore import ingest, ingest_recent
from ml.load_history import MIN_REAL_MATCHES, finished_matches_frame, load_csv
from ml.predict import predict_upcoming
from ml.train import train

INTERVAL_SECONDS = int(os.getenv("PREDICT_INTERVAL_SECONDS", "600"))
INGEST_EVERY = int(os.getenv("INGEST_INTERVAL_SECONDS", str(6 * 3600)))
RETRAIN_EVERY = int(os.getenv("RETRAIN_INTERVAL_SECONDS", str(24 * 3600)))


def _bootstrap() -> None:
    """First start: real history if the token allows it, otherwise the synthetic sample."""
    if PANDASCORE_TOKEN and len(finished_matches_frame("pandascore")) < MIN_REAL_MATCHES:
        print(f"history: ingested {ingest()}", flush=True)
    elif len(finished_matches_frame()) < 40:
        print(f"history: loaded {load_csv()} synthetic matches", flush=True)
    if not (ARTIFACTS_DIR / f"{XGB_MODEL_NAME}.joblib").exists():
        report = train()
        print(f"trained {report['model_name']} acc={report['accuracy']:.3f}", flush=True)


def run() -> None:
    last_ingest = last_train = time.monotonic()
    ready = False
    while True:
        try:
            if not ready:
                _bootstrap()
                ready = True
            now = time.monotonic()
            if PANDASCORE_TOKEN and now - last_ingest >= INGEST_EVERY:
                print(f"ingest recent: {ingest_recent()}", flush=True)
                last_ingest = now
            if now - last_train >= RETRAIN_EVERY:
                report = train()
                print(f"retrained acc={report['accuracy']:.3f}", flush=True)
                last_train = now
            print(f"predicted {predict_upcoming()} upcoming matches", flush=True)
        except Exception as exc:  # DB or API may not be ready yet
            print(f"worker: {exc}", flush=True)
        time.sleep(INTERVAL_SECONDS)
