"""Synthetic but Elo-consistent CS2-style history for local training (weeks 3–4).

Replace data/sample_matches.csv with a licensed Kaggle/Hugging Face export
when you have one. Do not scrape HLTV.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ml.config import SAMPLE_MATCHES_PATH

# Latent strength used only to simulate outcomes — never written as a feature.
TEAMS: dict[str, float] = {
    "Team Spirit": 1840,
    "Vitality": 1820,
    "MOUZ": 1785,
    "Falcons": 1765,
    "FURIA": 1745,
    "Natus Vincere": 1725,
    "G2": 1710,
    "The MongolZ": 1695,
    "Aurora": 1675,
    "Team Liquid": 1655,
    "FaZe": 1640,
    "Heroic": 1610,
    "Astralis": 1590,
    "Complexity": 1570,
    "paiN": 1555,
    "B8": 1540,
    "Legacy": 1525,
    "3DMAX": 1510,
    "BIG": 1495,
    "SAW": 1480,
    "Imperial": 1465,
    "M80": 1455,
    "Wildcard": 1445,
    "Rare Atom": 1435,
}

TOURNAMENTS = [
    ("BLAST Premier", "S"),
    ("ESL Pro League", "S"),
    ("IEM", "S"),
    ("CCT", "A"),
    ("Thunderpick", "A"),
    ("RES Regional", "B"),
]


def generate(n_matches: int = 480, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    names = list(TEAMS)
    start = datetime(2024, 3, 1, tzinfo=timezone.utc)
    rows: list[dict] = []
    for i in range(n_matches):
        t1, t2 = rng.sample(names, 2)
        r1, r2 = TEAMS[t1], TEAMS[t2]
        p1 = 1.0 / (1.0 + 10 ** ((r2 - r1) / 400.0))
        team1_wins = rng.random() < p1
        best_of = rng.choice([1, 3, 3, 3, 5])
        if best_of == 1:
            s1, s2 = (1, 0) if team1_wins else (0, 1)
        elif best_of == 3:
            s1, s2 = rng.choice([(2, 0), (2, 1)]) if team1_wins else rng.choice([(0, 2), (1, 2)])
        else:
            s1, s2 = rng.choice([(3, 0), (3, 1), (3, 2)]) if team1_wins else rng.choice([(0, 3), (1, 3), (2, 3)])
        tournament, tier = rng.choice(TOURNAMENTS)
        when = start + timedelta(hours=8 * i + rng.randint(0, 6))
        rows.append(
            {
                "match_id": f"sample-{i+1:04d}",
                "played_at": when.isoformat(),
                "team1": t1,
                "team2": t2,
                "score1": s1,
                "score2": s2,
                "best_of": best_of,
                "tournament": tournament,
                "tournament_tier": tier,
                "winner": t1 if team1_wins else t2,
            }
        )
    return pd.DataFrame(rows)


def write(path: Path | None = None, n_matches: int = 480) -> Path:
    dest = path or SAMPLE_MATCHES_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    generate(n_matches=n_matches).to_csv(dest, index=False)
    return dest
