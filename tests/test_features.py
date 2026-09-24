from datetime import datetime, timedelta, timezone

import pandas as pd

from ml.elo import expected_score, update
from ml.features import FEATURE_COLUMNS, build_pre_match_features


def test_elo_expected_is_symmetric():
    assert abs(expected_score(1600, 1500) + expected_score(1500, 1600) - 1.0) < 1e-9


def test_elo_winner_gains_rating():
    a, b = update(1500, 1500, True)
    assert a > 1500
    assert b < 1500


def test_features_do_not_use_current_match_outcome():
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    history = pd.DataFrame(
        [
            {
                "match_id": "m1",
                "played_at": t0,
                "team1": "A",
                "team2": "B",
                "winner": "A",
            },
            {
                "match_id": "m2",
                "played_at": t0 + timedelta(days=1),
                "team1": "A",
                "team2": "B",
                "winner": "B",
            },
        ]
    )
    feat = build_pre_match_features(history)
    first = feat.iloc[0]
    assert first["elo_diff"] == 0.0
    assert first["form5_diff"] == 0.0
    assert first["h2h_diff"] == 0.0
    second = feat.iloc[1]
    assert second["elo_diff"] != 0.0
    assert set(FEATURE_COLUMNS) <= set(feat.columns)
