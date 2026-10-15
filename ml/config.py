from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgres://cyber:cyber@localhost:55432/cyber_predict?sslmode=disable",
)
PANDASCORE_TOKEN = os.getenv("PANDASCORE_TOKEN", "").strip()
PANDASCORE_BASE_URL = os.getenv("PANDASCORE_BASE_URL", "https://api.pandascore.co").rstrip("/")
SAMPLE_MATCHES_PATH = Path(os.getenv("SAMPLE_MATCHES_PATH", ROOT / "data" / "sample_matches.csv"))
FIXTURES_PATH = Path(os.getenv("FIXTURES_PATH", ROOT / "data" / "fixtures" / "upcoming.json"))
ARTIFACTS_DIR = ROOT / "ml" / "artifacts"
MODEL_NAME = "elo_logreg"  # baseline
XGB_MODEL_NAME = "elo_xgboost"  # production model used for predictions
MODEL_VERSION = os.getenv("MODEL_VERSION", "0.2.0")
ELO_K = 20.0  # base step; tuned by walk-forward log-loss (was 32)
ELO_K_BOOST = 4.0  # newcomers move (1 + boost) times faster: K_team = K * (1 + boost / (1 + games / N0))
ELO_K_N0 = 5.0
ELO_MARGIN_WEIGHT = 0.5  # a 2:0 sweep counts up to +50% more than a 2:1
ELO_TIER_WEIGHT = 0.3  # S-tier matches weigh (1 + 0.3 * (tier - 2) / 4) relative to unknown tier
ELO_START = 1500.0
