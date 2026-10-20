"""Closed-form match outcome probabilities from remaining-goal intensities.

Given the current score and the expected number of goals each side will
score in the remainder of the match, remaining goals are modelled as two
independent Poisson variables. The probabilities are obtained from the
truncated joint distribution, so no simulation noise enters the Greeks.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 12


@dataclass(frozen=True)
class OutcomeProbs:
    p_home: float
    p_draw: float
    p_away: float

    def as_dict(self) -> dict:
        return {"p_home": round(self.p_home, 4), "p_draw": round(self.p_draw, 4), "p_away": round(self.p_away, 4)}

    def expected_points_home(self) -> float:
        return 3 * self.p_home + self.p_draw

    def expected_points_away(self) -> float:
        return 3 * self.p_away + self.p_draw


@lru_cache(maxsize=200_000)
def _probs_cached(home_goals: int, away_goals: int, lam_h_q: int, lam_a_q: int) -> OutcomeProbs:
    lam_h = lam_h_q / 1000.0
    lam_a = lam_a_q / 1000.0
    k = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(k, lam_h)
    pa = poisson.pmf(k, lam_a)
    ph[-1] += max(0.0, 1.0 - ph.sum())
    pa[-1] += max(0.0, 1.0 - pa.sum())
    joint = np.outer(ph, pa)
    margin = home_goals - away_goals
    i, j = np.meshgrid(k, k, indexing="ij")
    final_margin = margin + i - j
    p_home = float(joint[final_margin > 0].sum())
    p_draw = float(joint[final_margin == 0].sum())
    p_away = float(joint[final_margin < 0].sum())
    s = p_home + p_draw + p_away
    return OutcomeProbs(p_home / s, p_draw / s, p_away / s)


def outcome_probs(home_goals: int, away_goals: int, lam_h_remaining: float, lam_a_remaining: float) -> OutcomeProbs:
    """P(home win), P(draw), P(away win) given score and remaining expected goals.

    Intensities are quantised to 0.001 goals so repeated finite-difference
    calls hit the cache.
    """
    lam_h = max(0.0, float(lam_h_remaining))
    lam_a = max(0.0, float(lam_a_remaining))
    return _probs_cached(int(home_goals), int(away_goals), int(round(lam_h * 1000)), int(round(lam_a * 1000)))
