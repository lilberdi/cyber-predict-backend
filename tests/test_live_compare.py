import numpy as np

from ml.live_compare import _scores


def test_scores_match_hand_calculation():
    y = np.array([1, 0, 1, 0])
    p = np.array([0.8, 0.4, 0.4, 0.2])  # hits: yes, yes, no, yes
    s = _scores(y, p)
    assert s["accuracy"] == 0.75
    assert abs(s["brier"] - (0.04 + 0.16 + 0.36 + 0.04) / 4) < 1e-4
    ll = -(np.log(0.8) + np.log(0.6) + np.log(0.4) + np.log(0.8)) / 4
    assert abs(s["log_loss"] - round(ll, 4)) < 1e-4
