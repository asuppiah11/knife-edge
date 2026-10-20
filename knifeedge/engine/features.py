"""Public, documented feature formulas shared by the simulator and the engine.

These are deliberately simple and transparent so that every number an agent
cites can be reproduced from the event log by hand. The simulator's *hidden*
generating probabilities add unobserved terms (shooter finishing, defender
pressure) on top of these, so the engine is realistically mis-specified.
"""

from __future__ import annotations

import math

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
GOAL_X = 105.0
GOAL_Y = 34.0
GOAL_HALF_WIDTH = 3.66  # 7.32 m goal

BODY_PART_LOGIT = {"right_foot": 0.0, "left_foot": 0.0, "head": -0.55, "other": -0.3}
SITUATION_LOGIT = {"open_play": 0.0, "counter": 0.25, "set_piece": -0.15, "penalty": 0.0}


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def shot_geometry(x: float, y: float) -> tuple[float, float]:
    """Distance to goal centre (m) and angle subtended by the posts (rad)."""
    dx = GOAL_X - x
    dy = GOAL_Y - y
    dist = math.hypot(dx, dy)
    # angle between vectors to each post
    a1 = math.atan2(GOAL_Y + GOAL_HALF_WIDTH - y, dx)
    a2 = math.atan2(GOAL_Y - GOAL_HALF_WIDTH - y, dx)
    angle = abs(a1 - a2)
    return dist, angle


def xg_from_location(
    x: float,
    y: float,
    body_part: str = "right_foot",
    under_pressure: bool = False,
    situation: str = "open_play",
) -> float:
    """Observable xG: logistic in log-distance and goal angle.

    By construction (see docs/synthetic-data.md): ~0.21 from 12 m central,
    ~0.13 from 16 m, ~0.08 from 20 m, ~0.04 from 25 m, ~0.5 from 6 m central.
    """
    if situation == "penalty":
        return 0.76
    dist, angle = shot_geometry(x, y)
    dist = max(dist, 1.0)
    z = -0.45 - 0.12 * dist + 1.10 * angle
    z += BODY_PART_LOGIT.get(body_part, 0.0)
    z += SITUATION_LOGIT.get(situation, 0.0)
    if under_pressure:
        z -= 0.35
    return float(min(0.97, max(0.01, _sigmoid(z))))


def pass_difficulty(
    x: float,
    y: float,
    end_x: float,
    end_y: float,
    under_pressure: bool = False,
) -> float:
    """Probability a pass fails, from length, forwardness and zone."""
    length = math.hypot(end_x - x, end_y - y)
    forward = end_x - x
    forward_frac = max(0.0, forward) / max(length, 1.0)
    into_final_third = 1.0 if (end_x >= 70.0 and x < 70.0) else 0.0
    in_final_third = 1.0 if end_x >= 70.0 else 0.0
    z = -3.0 + 0.035 * length + 0.7 * forward_frac + 0.5 * into_final_third + 0.3 * in_final_third
    if under_pressure:
        z += 0.45
    return float(min(0.95, max(0.02, _sigmoid(z))))


def is_progressive(x: float, end_x: float) -> bool:
    """A pass or carry that moves the ball >= 10 m towards goal (simplified)."""
    return (end_x - x) >= 10.0
