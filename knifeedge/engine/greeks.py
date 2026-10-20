"""Greeks for a live football match.

The win probability of the home side, P, is a function of the match state.
Borrowing the language of option sensitivities:

* **Delta** - how much P moves for a unit change in the underlying. The
  natural underlying in football is a goal, so we report two deltas:
  ``delta_home_goal`` (P after a home goal minus P now) and
  ``delta_away_goal``. For a shot, its *expected* delta is ``xG × delta``.
* **Gamma** - convexity in the score margin:
  ``P(margin+1) - 2 P(margin) + P(margin-1)``. We also report the
  **knife-edge** reading, ``(|delta_home_goal| + |delta_away_goal|) / 2``,
  the expected absolute swing of the next goal. High = fragile.
* **Theta** - time decay: ``dP/dt`` per minute with the score held. For
  the side in front theta is positive: time is working for them.
* **Vega** - sensitivity to chaos: scale both sides' remaining intensities
  by a factor; ``vega = dP/d(chaos)``. A leader has negative vega - a more
  open game is a threat; a trailing side has positive vega.

All derivatives are finite differences on the closed-form probabilities in
``wp.py`` so they are exact for the model, not sampled.
"""

from __future__ import annotations

from dataclasses import dataclass

from .state import MatchState
from .wp import OutcomeProbs, outcome_probs


@dataclass(frozen=True)
class Greeks:
    p_home: float
    p_draw: float
    p_away: float
    delta_home_goal: float
    delta_away_goal: float
    gamma: float
    knife_edge: float
    theta_home: float
    theta_away: float
    vega_home: float
    vega_away: float
    next_goal_swing_home: float  # points (0-100)
    next_goal_swing_away: float

    def as_dict(self) -> dict:
        return {k: round(v, 4) for k, v in self.__dict__.items()}

    def points(self) -> dict:
        """Greeks expressed in probability points, convenient for narration."""
        return {
            "p_home": round(100 * self.p_home, 1),
            "p_draw": round(100 * self.p_draw, 1),
            "p_away": round(100 * self.p_away, 1),
            "delta_home_goal": round(100 * self.delta_home_goal, 1),
            "delta_away_goal": round(100 * self.delta_away_goal, 1),
            "gamma": round(100 * self.gamma, 1),
            "knife_edge": round(100 * self.knife_edge, 1),
            "theta_home": round(100 * self.theta_home, 2),
            "theta_away": round(100 * self.theta_away, 2),
            "vega_home": round(100 * self.vega_home, 1),
            "vega_away": round(100 * self.vega_away, 1),
            "next_goal_swing_home": round(self.next_goal_swing_home, 1),
            "next_goal_swing_away": round(self.next_goal_swing_away, 1),
        }


def probs_for(state: MatchState, home_goals: int | None = None, away_goals: int | None = None, elapsed_min: float | None = None, chaos: float = 1.0) -> OutcomeProbs:
    """Outcome probabilities for a (possibly hypothetical) variant of a state."""
    s = state if (home_goals is None and away_goals is None and elapsed_min is None) else state.copy()
    if home_goals is not None:
        s.home_goals = home_goals
    if away_goals is not None:
        s.away_goals = away_goals
    if elapsed_min is not None:
        s.elapsed_min = elapsed_min
    ih = s.intensity(s.home_id, chaos=chaos)
    ia = s.intensity(s.away_id, chaos=chaos)
    return outcome_probs(s.home_goals, s.away_goals, ih.lam_remaining, ia.lam_remaining)


def compute_greeks(state: MatchState, dt_min: float = 1.0, chaos_eps: float = 0.10) -> Greeks:
    now = probs_for(state)
    up = probs_for(state, home_goals=state.home_goals + 1)
    down = probs_for(state, away_goals=state.away_goals + 1)
    later = probs_for(state, elapsed_min=min(state.elapsed_min + dt_min, 95.2))
    hi = probs_for(state, chaos=1.0 + chaos_eps)
    lo = probs_for(state, chaos=1.0 - chaos_eps)

    delta_hg = up.p_home - now.p_home
    delta_ag = down.p_home - now.p_home
    gamma = up.p_home - 2 * now.p_home + down.p_home
    knife = 0.5 * (abs(delta_hg) + abs(delta_ag))
    theta_h = (later.p_home - now.p_home) / dt_min
    theta_a = (later.p_away - now.p_away) / dt_min
    vega_h = (hi.p_home - lo.p_home) / (2 * chaos_eps)
    vega_a = (hi.p_away - lo.p_away) / (2 * chaos_eps)
    return Greeks(
        p_home=now.p_home,
        p_draw=now.p_draw,
        p_away=now.p_away,
        delta_home_goal=delta_hg,
        delta_away_goal=delta_ag,
        gamma=gamma,
        knife_edge=knife,
        theta_home=theta_h,
        theta_away=theta_a,
        vega_home=vega_h,
        vega_away=vega_a,
        next_goal_swing_home=100 * abs(delta_hg),
        next_goal_swing_away=100 * abs(delta_ag),
    )


def expected_shot_delta(state: MatchState, team_id: str, xg: float) -> float:
    """Expected change in P(home win) from a shot of the given xG, before the outcome is known."""
    g = compute_greeks(state)
    d = g.delta_home_goal if team_id == state.home_id else g.delta_away_goal
    return xg * d
