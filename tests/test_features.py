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


def _hist(rows):
    return pd.DataFrame(rows)


def test_new_features_use_only_the_past():
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    base = [
        {"match_id": "m1", "played_at": t0, "team1": "A", "team2": "B", "winner": "A", "score1": 2, "score2": 0},
        {"match_id": "m2", "played_at": t0 + timedelta(days=3), "team1": "A", "team2": "B", "winner": "B", "score1": 0, "score2": 2},
    ]
    feat = build_pre_match_features(_hist(base))
    first, second = feat.iloc[0], feat.iloc[1]
    assert first["ewm_form_diff"] == 0 and first["margin_diff"] == 0  # nothing known yet
    assert second["rest_diff"] == 0  # both rested the same 3 days
    assert second["margin_diff"] > 0  # A won 2-0 before
    assert second["ewm_form_diff"] > 0
    # changing match 2's winner must not change match 2's features
    flipped = [dict(base[0]), {**base[1], "winner": "A", "score1": 2, "score2": 0}]
    assert build_pre_match_features(_hist(flipped)).iloc[1]["margin_diff"] == second["margin_diff"]


def test_rest_diff_prefers_the_rested_team():
    from ml.features import TeamBook

    t0 = pd.Timestamp("2025-01-10", tz="UTC")
    book = TeamBook()
    book.update("A", "X", t0 - pd.Timedelta(days=1), True)
    book.update("B", "Y", t0 - pd.Timedelta(days=9), True)
    assert book.features("A", "B", t0)["rest_diff"] == -8.0


def test_normalize_finished_filters_bad_rows():
    from ml.history_pandascore import normalize_finished

    good = {
        "id": 1, "begin_at": "2026-01-01T10:00:00Z", "winner_id": 11, "number_of_games": 3,
        "opponents": [{"opponent": {"id": 11, "name": "A"}}, {"opponent": {"id": 12, "name": "B"}}],
        "results": [{"team_id": 11, "score": 2}, {"team_id": 12, "score": 1}],
        "tournament": {"name": "Cup", "tier": "A"},
    }
    m = normalize_finished(good)
    assert m["score1"] == 2 and m["score2"] == 1 and m["tier"] == "a"
    assert normalize_finished({**good, "forfeit": True}) is None
    assert normalize_finished({**good, "winner_id": 99}) is None
    assert normalize_finished({**good, "begin_at": None}) is None
    assert normalize_finished({**good, "opponents": good["opponents"][:1]}) is None


def test_calibrator_choice_defaults_to_raw_on_small_data():
    import numpy as np

    from ml.train import _choose_calibrator

    assert _choose_calibrator(np.array([0.4, 0.6] * 10), np.array([0, 1] * 10)) == "raw"


def test_elo_upset_gains_more_than_even_match():
    from ml.elo import EloBook

    even = EloBook.fresh()
    even.apply("A", "B", True)
    upset = EloBook.fresh()
    upset.ratings.update({"A": 1400.0, "B": 1600.0})
    upset.apply("A", "B", True)
    assert upset.ratings["A"] - 1400.0 > even.ratings["A"] - 1500.0


def test_elo_newcomer_moves_faster_and_sweep_counts_more():
    from ml.elo import EloBook

    book = EloBook.fresh()
    book.played["VET"] = 200
    assert book.team_k("NEW") > book.team_k("VET")
    close, sweep = EloBook.fresh(), EloBook.fresh()
    close.apply("A", "B", True, margin=1 / 3)
    sweep.apply("A", "B", True, margin=1.0)
    assert sweep.ratings["A"] > close.ratings["A"]


def test_roster_plan_join_transfer_leave():
    from ml.rosters import Op, plan_changes

    open_rows = {"a": 1, "b": 1, "c": 1}
    desired = {"a": [1], "b": [2], "d": [2]}
    ops = plan_changes(open_rows, desired, tracked={1, 2})
    assert Op("transfer", "b", 1, 2) in ops
    assert Op("join", "d", None, 2) in ops
    assert Op("leave", "c", 1, None) in ops
    assert not any(o.player == "a" for o in ops)


def test_roster_plan_keeps_player_listed_by_two_teams_and_guards_empty_team():
    from ml.rosters import Op, plan_changes

    assert plan_changes({"a": 1}, {"a": [2, 1]}, {1, 2}) == []
    assert plan_changes({"a": 1}, {}, {1}, skip_leave_teams={1}) == []
    assert plan_changes({"a": 9}, {}, {1}) == []  # untracked team: no verdict
    assert plan_changes({"a": 1}, {}, {1}) == [Op("leave", "a", 1, None)]


def test_player_rating_transfer_changes_team_strength_and_conserves_points():
    from ml.player_rating import pick_lineup, rate_match

    team1 = [(i, 1500.0, 30) for i in range(5)]
    team2 = [(10 + i, 1500.0, 30) for i in range(5)]
    d = rate_match(team1, team2, True)
    assert all(v > 0 for k, v in d.items() if k < 10) and all(v < 0 for k, v in d.items() if k >= 10)
    assert abs(sum(d.values())) < 1e-9  # equal K: symmetric
    star = [(0, 1900.0, 30)] + team1[1:]
    assert rate_match(star, team2, True)[0] < d[0]  # favourite wins -> smaller gain
    newcomer = [(99, 1500.0, 0)] + team1[1:]
    assert rate_match(newcomer, team2, True)[99] > d[1]  # newcomers move faster
    assert len(pick_lineup([(i, 1500.0 + i, i) for i in range(8)])) == 5
