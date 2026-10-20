"""Greeks MCP server: the engine as tools for agents (Agent Framework, Foundry agents, Copilot).

Tools
-----
list_matches()                      -> matches available in the store
greeks_now(match_id, minute)        -> probabilities, Delta/Gamma/Theta/Vega and the intensity breakdown
why_it_moved(match_id, event_id)    -> swing decomposition + evidence for one event
top_moments(match_id, n, kind)      -> biggest realised or expected moments
theta_curve(match_id)               -> theta and fragility per minute
scenario(match_id, minute, ...)     -> what-if: a goal, a red card, more chaos

Run stand-alone:   python -m knifeedge.api.mcp_server  (stdio)
Mounted in the API: /mcp (streamable HTTP) by knifeedge.api.app
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .store import MatchStore

_store: Optional[MatchStore] = None


def get_store() -> MatchStore:
    global _store
    if _store is None:
        _store = MatchStore(Path(os.environ.get("KNIFE_EDGE_MATCHES", "data/matches")), Path(os.environ.get("KNIFE_EDGE_RATINGS", "data/ratings.json")))
    return _store


def build_mcp():
    try:  # mcp >= 2.0
        from mcp.server.mcpserver import MCPServer as _Server
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP as _Server

    mcp = _Server("knife-edge-greeks", instructions="Live football match sensitivities (Delta, Gamma, Theta, Vega) over synthetic matches. All data is synthetic. Never use betting language.")

    @mcp.tool()
    def list_matches() -> list[dict]:
        """List the synthetic matches available."""
        return get_store().list()

    @mcp.tool()
    def greeks_now(match_id: str, minute: Optional[float] = None) -> dict:
        """Outcome probabilities and Greeks at a minute (default: latest)."""
        return get_store().replay(match_id).greeks_now(minute)

    @mcp.tool()
    def why_it_moved(match_id: str, event_id: int) -> dict:
        """Decompose the probability swing of one event into time, momentum, discipline and score, with evidence."""
        return get_store().replay(match_id).why_it_moved(event_id)

    @mcp.tool()
    def top_moments(match_id: str, n: int = 5, kind: str = "realised") -> list[dict]:
        """Biggest moments. kind='realised' (|swing|) or 'expected' (|xG x delta| for shots)."""
        return get_store().replay(match_id).top_moments(n, kind)

    @mcp.tool()
    def theta_curve(match_id: str) -> list[dict]:
        """Theta (points per minute) and knife-edge per minute."""
        return get_store().replay(match_id).theta_curve()

    @mcp.tool()
    def scenario(match_id: str, minute: float, home_goal: int = 0, away_goal: int = 0, red_home: int = 0, red_away: int = 0, chaos: float = 1.0) -> dict:
        """What-if at a minute: extra goals, red cards, or a chaos multiplier on both intensities."""
        return get_store().replay(match_id).scenario(minute, home_goal, away_goal, red_home, red_away, chaos)

    return mcp


if __name__ == "__main__":  # pragma: no cover
    build_mcp().run()
