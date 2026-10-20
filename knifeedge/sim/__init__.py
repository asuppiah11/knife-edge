"""Synthetic data generation. Everything here is seeded and deterministic."""

from .league import League, Team, Player, build_league
from .match import MatchSimulator, SimConfig, simulate_match

__all__ = [
    "League",
    "Team",
    "Player",
    "build_league",
    "MatchSimulator",
    "SimConfig",
    "simulate_match",
]
