"""Pre-match features only. Never use score/winner/ADR from the current match."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta

import pandas as pd

from ml.elo import EloBook


FEATURE_COLUMNS = ["elo_diff", "form5_diff", "form10_diff", "h2h_diff"]


def build_pre_match_features(history: pd.DataFrame) -> pd.DataFrame:
    """history must be sorted by played_at and already finished.

    For each row, features are computed from *previous* matches only.
    """
    df = history.sort_values("played_at").reset_index(drop=True).copy()
    book = EloBook.fresh()
    last_results: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=10))
    h2h_wins: dict[tuple[str, str], list[tuple[pd.Timestamp, int]]] = defaultdict(list)

    rows: list[dict] = []
    for row in df.itertuples(index=False):
        t1, t2 = row.team1, row.team2
        when = pd.Timestamp(row.played_at)
        r1, r2 = book.rating(t1), book.rating(t2)
        form5_1 = _form(last_results[t1], 5)
        form5_2 = _form(last_results[t2], 5)
        form10_1 = _form(last_results[t1], 10)
        form10_2 = _form(last_results[t2], 10)
        h2h = _h2h(h2h_wins, t1, t2, when)

        team1_won = row.winner == t1
        rows.append(
            {
                "match_id": row.match_id,
                "played_at": when,
                "team1": t1,
                "team2": t2,
                "team1_win": int(team1_won),
                "elo_team1": r1,
                "elo_team2": r2,
                "elo_diff": r1 - r2,
                "form5_diff": form5_1 - form5_2,
                "form10_diff": form10_1 - form10_2,
                "h2h_diff": h2h,
            }
        )

        book.apply(t1, t2, team1_won)
        last_results[t1].append(1 if team1_won else 0)
        last_results[t2].append(0 if team1_won else 1)
        h2h_wins[(t1, t2)].append((when, 1 if team1_won else 0))
        h2h_wins[(t2, t1)].append((when, 0 if team1_won else 1))

    return pd.DataFrame(rows)


def snapshot_for_upcoming(history: pd.DataFrame, team1: str, team2: str, when: pd.Timestamp) -> dict[str, float]:
    """Features for an upcoming match using only history with played_at < when."""
    past = history[pd.to_datetime(history["played_at"]) < when].sort_values("played_at")
    book = EloBook.fresh()
    last_results: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=10))
    h2h_wins: dict[tuple[str, str], list[tuple[pd.Timestamp, int]]] = defaultdict(list)
    for row in past.itertuples(index=False):
        t1, t2 = row.team1, row.team2
        ts = pd.Timestamp(row.played_at)
        team1_won = row.winner == t1
        book.apply(t1, t2, team1_won)
        last_results[t1].append(1 if team1_won else 0)
        last_results[t2].append(0 if team1_won else 1)
        h2h_wins[(t1, t2)].append((ts, 1 if team1_won else 0))
        h2h_wins[(t2, t1)].append((ts, 0 if team1_won else 1))

    r1, r2 = book.rating(team1), book.rating(team2)
    return {
        "elo_team1": r1,
        "elo_team2": r2,
        "elo_diff": r1 - r2,
        "form5_diff": _form(last_results[team1], 5) - _form(last_results[team2], 5),
        "form10_diff": _form(last_results[team1], 10) - _form(last_results[team2], 10),
        "h2h_diff": _h2h(h2h_wins, team1, team2, when),
    }


def _form(results: deque[int], n: int) -> float:
    if not results:
        return 0.5
    window = list(results)[-n:]
    return sum(window) / len(window)


def _h2h(store: dict, t1: str, t2: str, when: pd.Timestamp) -> float:
    cutoff = when - timedelta(days=365)
    games = [won for ts, won in store.get((t1, t2), []) if cutoff <= ts < when]
    if not games:
        return 0.0
    return sum(games) / len(games) - 0.5
