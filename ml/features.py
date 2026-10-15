"""Pre-match features only. Never use score/winner/ADR from the current match."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta

import pandas as pd

from ml.elo import EloBook

FEATURE_COLUMNS = ["elo_diff", "form5_diff", "form10_diff", "h2h_diff"]
# Extra signals only XGBoost sees. Each one is checked by an ablation in train.py.
EXTRA_FEATURES = ["exp_diff", "best_of", "tier", "ewm_form_diff", "rest_diff", "margin_diff"]
XGB_FEATURE_COLUMNS = FEATURE_COLUMNS + EXTRA_FEATURES

EWM_ALPHA = 0.25  # weight of the newest result in the exponentially weighted form
REST_CAP_DAYS = 30.0
H2H_WINDOW_DAYS = 365

# Live PandaScore names -> names used in history (lowercase keys).
TEAM_ALIASES = {
    "nip": "ninjas in pyjamas",
    "liquid": "team liquid",
    "navi": "natus vincere",
    "natus vincere junior": "natus vincere",
    "themongolz": "the mongolz",
    "aurora gaming": "aurora",
    "faze clan": "faze",
    "spirit": "team spirit",
    "vitality.": "vitality",
}

_TIERS = {"s": 4, "a": 3, "b": 2, "c": 1, "d": 0}


def tier_value(tier) -> int:
    """Tournament prestige: S=4 ... D=0; unknown -> 2."""
    return _TIERS.get(str(tier).strip().lower(), 2) if tier is not None and tier == tier else 2


def resolve_team(name: str, history: pd.DataFrame) -> str:
    """Map a live team name onto the spelling used in history (case/alias tolerant)."""
    known = {n.lower(): n for n in pd.concat([history["team1"], history["team2"]]).unique()}
    key = name.strip().lower()
    key = TEAM_ALIASES.get(key, key)
    return known.get(key, name)


def _form(results: deque[int], n: int) -> float:
    if not results:
        return 0.5
    window = list(results)[-n:]
    return sum(window) / len(window)


class TeamBook:
    """Rolling state of every team; features() reads it, update() advances it."""

    def __init__(self) -> None:
        self.elo = EloBook.fresh()
        self.results: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=10))
        self.margins: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=10))
        self.ewm: dict[str, float] = {}
        self.last_played: dict[str, pd.Timestamp] = {}
        self.h2h: dict[tuple[str, str], list[tuple[pd.Timestamp, int]]] = defaultdict(list)

    def games(self, team: str) -> int:
        return self.elo.played.get(team, 0)

    def _h2h(self, t1: str, t2: str, when: pd.Timestamp) -> float:
        cutoff = when - timedelta(days=H2H_WINDOW_DAYS)
        wins = [w for ts, w in self.h2h.get((t1, t2), []) if cutoff <= ts < when]
        return sum(wins) / len(wins) - 0.5 if wins else 0.0

    def _rest(self, team: str, when: pd.Timestamp) -> float:
        last = self.last_played.get(team)
        return REST_CAP_DAYS if last is None else min(REST_CAP_DAYS, max(0.0, (when - last).total_seconds() / 86400))

    def features(self, t1: str, t2: str, when: pd.Timestamp, best_of=3, tier=None) -> dict[str, float]:
        r1, r2 = self.elo.rating(t1), self.elo.rating(t2)
        margin = lambda t: sum(self.margins[t]) / len(self.margins[t]) if self.margins[t] else 0.0  # noqa: E731
        return {
            "elo_team1": r1,
            "elo_team2": r2,
            "elo_diff": r1 - r2,
            "form5_diff": _form(self.results[t1], 5) - _form(self.results[t2], 5),
            "form10_diff": _form(self.results[t1], 10) - _form(self.results[t2], 10),
            "h2h_diff": self._h2h(t1, t2, when),
            "exp_diff": self.games(t1) - self.games(t2),
            "best_of": int(best_of or 3),
            "tier": tier_value(tier),
            "ewm_form_diff": self.ewm.get(t1, 0.5) - self.ewm.get(t2, 0.5),
            "rest_diff": self._rest(t1, when) - self._rest(t2, when),
            "margin_diff": margin(t1) - margin(t2),
            "games_team1": self.games(t1),
            "games_team2": self.games(t2),
        }

    def update(self, t1: str, t2: str, when: pd.Timestamp, team1_won: bool, score1=None, score2=None) -> None:
        self.elo.apply(t1, t2, team1_won)
        for team, won in ((t1, team1_won), (t2, not team1_won)):
            self.results[team].append(int(won))
            prev = self.ewm.get(team, 0.5)
            self.ewm[team] = prev + EWM_ALPHA * (int(won) - prev)
            self.last_played[team] = when
        if score1 is not None and score2 is not None and score1 == score1 and score2 == score2 and score1 + score2 > 0:
            m = (float(score1) - float(score2)) / (float(score1) + float(score2))
            self.margins[t1].append(m)
            self.margins[t2].append(-m)
        self.h2h[(t1, t2)].append((when, int(team1_won)))
        self.h2h[(t2, t1)].append((when, int(not team1_won)))


def build_book(history: pd.DataFrame, before: pd.Timestamp | None = None) -> TeamBook:
    """Replay finished matches (optionally only those strictly before `before`)."""
    df = history.sort_values("played_at")
    if before is not None:
        df = df[pd.to_datetime(df["played_at"]) < before]
    book = TeamBook()
    for row in df.itertuples(index=False):
        book.update(
            row.team1, row.team2, pd.Timestamp(row.played_at), row.winner == row.team1,
            getattr(row, "score1", None), getattr(row, "score2", None),
        )
    return book


def build_pre_match_features(history: pd.DataFrame) -> pd.DataFrame:
    """history must be finished matches. Each row's features use *previous* matches only."""
    df = history.sort_values("played_at").reset_index(drop=True)
    book = TeamBook()
    rows: list[dict] = []
    for row in df.itertuples(index=False):
        t1, t2 = row.team1, row.team2
        when = pd.Timestamp(row.played_at)
        feat = book.features(t1, t2, when, getattr(row, "best_of", 3), getattr(row, "tournament_tier", None))
        team1_won = row.winner == t1
        rows.append({"match_id": row.match_id, "played_at": when, "team1": t1, "team2": t2, "team1_win": int(team1_won), **feat})
        book.update(t1, t2, when, team1_won, getattr(row, "score1", None), getattr(row, "score2", None))
    return pd.DataFrame(rows)


def snapshot_for_upcoming(
    history: pd.DataFrame, team1: str, team2: str, when: pd.Timestamp, best_of: int = 3, tier=None,
    book: TeamBook | None = None,
) -> dict[str, float]:
    """Features for an upcoming match using only history with played_at < when.

    Pass a prebuilt `book` (see build_book) to avoid replaying history for every match.
    """
    team1, team2 = resolve_team(team1, history), resolve_team(team2, history)
    book = book or build_book(history, before=when)
    return book.features(team1, team2, when, best_of, tier)
