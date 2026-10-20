"""Knife-Edge: live football match intelligence measured in sensitivities.

Packages
--------
sim     - seeded synthetic league and event-level match generator (with hidden truth)
engine  - ratings, win-probability model, Greeks (Delta/Gamma/Theta/Vega), replay
agents  - cue contract, deterministic Verifier, template fallback, Agent Framework runner
api     - FastAPI service and MCP tool server exposing the engine

All data produced by this package is synthetic. No real competition, club,
player or match is represented.
"""

__version__ = "0.1.0"
