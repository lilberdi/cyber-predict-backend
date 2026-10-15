from __future__ import annotations

from dataclasses import dataclass

from ml.config import ELO_K, ELO_K_BOOST, ELO_K_N0, ELO_MARGIN_WEIGHT, ELO_START, ELO_TIER_WEIGHT


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update(rating_a: float, rating_b: float, a_won: bool, k: float = ELO_K) -> tuple[float, float]:
    exp_a = expected_score(rating_a, rating_b)
    score_a = 1.0 if a_won else 0.0
    new_a = rating_a + k * (score_a - exp_a)
    new_b = rating_b + k * ((1.0 - score_a) - (1.0 - exp_a))
    return new_a, new_b


@dataclass
class EloBook:
    ratings: dict[str, float]
    played: dict[str, int]

    @classmethod
    def fresh(cls) -> "EloBook":
        return cls(ratings={}, played={})

    def rating(self, team: str) -> float:
        return self.ratings.get(team, ELO_START)

    def team_k(self, team: str) -> float:
        """Newcomers have an unreliable rating, so they move faster."""
        return ELO_K * (1.0 + ELO_K_BOOST / (1.0 + self.played.get(team, 0) / ELO_K_N0))

    def apply(self, team1: str, team2: str, team1_won: bool, margin: float = 0.0, tier: int = 2) -> None:
        """margin = |s1 - s2| / (s1 + s2) in [0, 1]; tier is S=4 ... D=0 (2 = unknown)."""
        r1, r2 = self.rating(team1), self.rating(team2)
        weight = (1.0 + ELO_MARGIN_WEIGHT * margin) * (1.0 + ELO_TIER_WEIGHT * (tier - 2) / 4.0)
        delta = (1.0 if team1_won else 0.0) - expected_score(r1, r2)
        self.ratings[team1] = r1 + self.team_k(team1) * weight * delta
        self.ratings[team2] = r2 - self.team_k(team2) * weight * delta
        self.played[team1] = self.played.get(team1, 0) + 1
        self.played[team2] = self.played.get(team2, 0) + 1
