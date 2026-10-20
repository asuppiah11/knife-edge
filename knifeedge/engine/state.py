"""Match state as the engine sees it, and the live intensity estimate.

The engine never reads truth.json. It knows: pre-match expected goals from
the ratings model, the score, the clock, cards, and what it can compute
from the event log (recent xG, field tilt, pressures). Every multiplier it
applies is stored so an explanation can cite it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional
from collections import deque

# Model assumption: a match lasts 90 minutes plus ~5.5 minutes of stoppage in total.
TOTAL_MINUTES = 95.5
MIN_REMAINING = 0.3
MOMENTUM_WINDOW_MIN = 10.0
MOMENTUM_GAIN = 0.20  # how strongly recent chance quality moves the intensity estimate
MOMENTUM_CLIP = (0.88, 1.15)

# The engine's own score-state multipliers (deliberately not identical to the simulator's).
SCORE_STATE_MULT = {2: 0.85, 1: 0.92, 0: 1.00, -1: 1.18, -2: 1.25}
RED_CARD_OWN = 0.70
RED_CARD_OPP = 1.25


def score_state_mult(lead: int) -> float:
    lead = max(-2, min(2, lead))
    return SCORE_STATE_MULT[lead]


@dataclass
class LiveIntensity:
    """Per-team remaining-goal intensity with its explanation."""

    team_id: str
    prior_per_90: float
    score_mult: float
    men_mult: float
    momentum_mult: float
    tilt_mult: float
    rate_per_min: float
    remaining_min: float
    lam_remaining: float
    recent_xg: float
    expected_recent_xg: float
    recent_tilt: float

    def as_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "prior_per_90": round(self.prior_per_90, 3),
            "score_mult": round(self.score_mult, 3),
            "men_mult": round(self.men_mult, 3),
            "momentum_mult": round(self.momentum_mult, 3),
            "tilt_mult": round(self.tilt_mult, 3),
            "rate_per_min": round(self.rate_per_min, 5),
            "remaining_min": round(self.remaining_min, 2),
            "lam_remaining": round(self.lam_remaining, 4),
            "recent_xg": round(self.recent_xg, 3),
            "expected_recent_xg": round(self.expected_recent_xg, 3),
            "recent_tilt": round(self.recent_tilt, 3),
        }


@dataclass
class MatchState:
    home_id: str
    away_id: str
    prior_home_90: float
    prior_away_90: float
    elapsed_min: float = 0.0
    home_goals: int = 0
    away_goals: int = 0
    home_men: int = 11
    away_men: int = 11
    # rolling evidence windows: (clock_min, value, event_id)
    recent_shots: Dict[str, Deque] = field(default_factory=dict)
    recent_touches: Dict[str, Deque] = field(default_factory=dict)  # (clock_min, in_final_third, event_id)
    momentum_on: bool = True

    def __post_init__(self) -> None:
        for tid in (self.home_id, self.away_id):
            self.recent_shots.setdefault(tid, deque())
            self.recent_touches.setdefault(tid, deque())

    # ------------------------------------------------------------- helpers
    def copy(self) -> "MatchState":
        s = MatchState(self.home_id, self.away_id, self.prior_home_90, self.prior_away_90, self.elapsed_min, self.home_goals, self.away_goals, self.home_men, self.away_men, momentum_on=self.momentum_on)
        for tid in (self.home_id, self.away_id):
            s.recent_shots[tid] = deque(self.recent_shots[tid])
            s.recent_touches[tid] = deque(self.recent_touches[tid])
        return s

    def opp(self, tid: str) -> str:
        return self.away_id if tid == self.home_id else self.home_id

    def goals(self, tid: str) -> int:
        return self.home_goals if tid == self.home_id else self.away_goals

    def men(self, tid: str) -> int:
        return self.home_men if tid == self.home_id else self.away_men

    def prior(self, tid: str) -> float:
        return self.prior_home_90 if tid == self.home_id else self.prior_away_90

    def remaining_min(self) -> float:
        return max(MIN_REMAINING, TOTAL_MINUTES - self.elapsed_min)

    # ------------------------------------------------------------ evidence
    def add_shot(self, tid: str, clock_min: float, xg: float, event_id: int) -> None:
        self.recent_shots[tid].append((clock_min, xg, event_id))
        self._trim(clock_min)

    def add_touch(self, tid: str, clock_min: float, in_final_third: bool, event_id: int) -> None:
        self.recent_touches[tid].append((clock_min, in_final_third, event_id))
        self._trim(clock_min)

    def _trim(self, clock_min: float) -> None:
        cutoff = clock_min - MOMENTUM_WINDOW_MIN
        for tid in (self.home_id, self.away_id):
            dq = self.recent_shots[tid]
            while dq and dq[0][0] < cutoff:
                dq.popleft()
            dq = self.recent_touches[tid]
            while dq and dq[0][0] < cutoff:
                dq.popleft()

    def recent_xg(self, tid: str) -> float:
        """Age-weighted xG in the window: a chance counts fully when fresh and fades linearly to zero at 10 min."""
        now = self.elapsed_min
        total = 0.0
        for t, v, _ in self.recent_shots[tid]:
            age = max(0.0, now - t)
            total += v * max(0.0, 1.0 - age / MOMENTUM_WINDOW_MIN)
        return float(total)

    def recent_shot_ids(self, tid: str) -> List[int]:
        return [eid for _, _, eid in self.recent_shots[tid]]

    def recent_tilt(self, tid: str) -> float:
        """Share of final-third touches in the window: own / (own + opp). 0.5 = neutral."""
        own = sum(1 for _, f, _ in self.recent_touches[tid] if f)
        opp = sum(1 for _, f, _ in self.recent_touches[self.opp(tid)] if f)
        if own + opp < 6:
            return 0.5
        return own / (own + opp)

    # ----------------------------------------------------------- intensity
    def intensity(self, tid: str, chaos: float = 1.0, momentum_override: Optional[float] = None) -> LiveIntensity:
        opp = self.opp(tid)
        lead = self.goals(tid) - self.goals(opp)
        score_mult = score_state_mult(lead)
        men_mult = (RED_CARD_OWN ** (11 - self.men(tid))) * (RED_CARD_OPP ** (11 - self.men(opp)))
        prior90 = self.prior(tid)
        window = min(MOMENTUM_WINDOW_MIN, max(self.elapsed_min, 1.0))
        # age-weighted window integrates to window/2 of a flat rate
        expected_recent = prior90 / 90.0 * (window / 2.0) * score_mult * men_mult
        recent = self.recent_xg(tid)
        tilt = self.recent_tilt(tid)
        if self.momentum_on:
            # ramp the evidence weight in over the first 10 minutes so there is no discontinuity at kick-off
            ramp = min(1.0, self.elapsed_min / MOMENTUM_WINDOW_MIN)
            raw = 1.0 + MOMENTUM_GAIN * (recent - expected_recent) / (expected_recent + 0.25)
            momentum_mult = 1.0 + ramp * (float(min(MOMENTUM_CLIP[1], max(MOMENTUM_CLIP[0], raw))) - 1.0)
            tilt_mult = 1.0 + ramp * (float(min(1.05, max(0.95, 1.0 + 0.25 * (tilt - 0.5)))) - 1.0)
        else:
            momentum_mult, tilt_mult = 1.0, 1.0
        if momentum_override is not None:
            momentum_mult = momentum_override
        rate = prior90 / 90.0 * score_mult * men_mult * momentum_mult * tilt_mult * chaos
        rem = self.remaining_min()
        return LiveIntensity(tid, prior90, score_mult, men_mult, momentum_mult, tilt_mult, rate, rem, rate * rem, recent, expected_recent, tilt)
