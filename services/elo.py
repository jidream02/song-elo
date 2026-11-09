"""Чистая математика Elo — без БД и сети, поэтому легко тестируется."""

from __future__ import annotations

from dataclasses import dataclass

BASE_RATING = 1500.0
K_DEFAULT = 32
K_NEW = 48
PROVISIONAL_MATCHES = 10  # меньше стольких матчей — песня «новая», K повышен

# Опорные точки перевода оценки 1–10 в Elo (между ними — линейно).
SCORE_MIN, ELO_MIN = 1.0, 800
SCORE_MID, ELO_MID = 5.0, 1500
SCORE_MAX, ELO_MAX = 10.0, 2200


def expected_score(rating_a: float, rating_b: float) -> float:
    """Вероятность победы A над B по формуле Elo."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def k_factor(matches: int) -> int:
    return K_NEW if matches < PROVISIONAL_MATCHES else K_DEFAULT


def is_provisional(matches: int) -> bool:
    return matches < PROVISIONAL_MATCHES


@dataclass(frozen=True)
class EloUpdate:
    old_a: float
    old_b: float
    new_a: float
    new_b: float

    @property
    def delta_a(self) -> float:
        return self.new_a - self.old_a

    @property
    def delta_b(self) -> float:
        return self.new_b - self.old_b


def update_ratings(
    rating_a: float,
    rating_b: float,
    score_a: float,
    matches_a: int = PROVISIONAL_MATCHES,
    matches_b: int = PROVISIONAL_MATCHES,
) -> EloUpdate:
    """Пересчёт после матча. score_a: 1 — победа A, 0 — победа B, 0.5 — ничья.

    У каждой песни свой K: новая песня (< 10 матчей) двигается быстрее,
    поэтому сумма рейтингов при разных K не обязана сохраняться.
    """
    if not 0.0 <= score_a <= 1.0:
        raise ValueError("score_a must be in [0, 1]")
    exp_a = expected_score(rating_a, rating_b)
    exp_b = 1.0 - exp_a
    score_b = 1.0 - score_a
    new_a = rating_a + k_factor(matches_a) * (score_a - exp_a)
    new_b = rating_b + k_factor(matches_b) * (score_b - exp_b)
    return EloUpdate(old_a=rating_a, old_b=rating_b, new_a=new_a, new_b=new_b)


def score_to_elo(score: float) -> int:
    """Средний балл 1–10 → Elo: 1 ≈ 800, 5 ≈ 1500, 10 ≈ 2200."""
    s = min(max(score, SCORE_MIN), SCORE_MAX)
    if s <= SCORE_MID:
        frac = (s - SCORE_MIN) / (SCORE_MID - SCORE_MIN)
        value = ELO_MIN + frac * (ELO_MID - ELO_MIN)
    else:
        frac = (s - SCORE_MID) / (SCORE_MAX - SCORE_MID)
        value = ELO_MID + frac * (ELO_MAX - ELO_MID)
    return round(value)


def win_probability(rating_a: float, rating_b: float) -> float:
    """Синоним expected_score для читаемости в /compare."""
    return expected_score(rating_a, rating_b)
