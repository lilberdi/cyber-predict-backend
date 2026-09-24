"""Week 3–4 EDA. Run: python notebooks/01_eda.py (needs loaded history or sample CSV)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.config import SAMPLE_MATCHES_PATH  # noqa: E402
from ml.features import build_pre_match_features  # noqa: E402
from ml.generate_sample import write  # noqa: E402


def main() -> None:
    if not SAMPLE_MATCHES_PATH.exists():
        write()
    df = pd.read_csv(SAMPLE_MATCHES_PATH, parse_dates=["played_at"])
    print("rows", len(df))
    print("teams", pd.unique(pd.concat([df["team1"], df["team2"]])).size)
    print("date range", df["played_at"].min(), "→", df["played_at"].max())
    print("team1 win rate", (df["winner"] == df["team1"]).mean().round(3))
    print("\nmatches per tournament")
    print(df["tournament"].value_counts().to_string())
    feat = build_pre_match_features(df)
    print("\nfeature describe")
    print(feat[["elo_diff", "form5_diff", "form10_diff", "h2h_diff", "team1_win"]].describe().round(3))


if __name__ == "__main__":
    main()
