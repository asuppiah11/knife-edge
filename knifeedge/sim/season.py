"""Generate a synthetic season of results for fitting pre-match ratings.

Results come from the same strengths the match generator uses, but at
match level (two Poisson draws), so the engine's ratings are fitted on
"history" rather than being handed the truth.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from .league import League, build_league


def generate_season(league: League, seed: int = 11, double_round_robin: bool = True) -> List[Tuple[str, str, int, int]]:
    rng = np.random.default_rng(seed)
    results: List[Tuple[str, str, int, int]] = []
    n = len(league.teams)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if not double_round_robin and i > j:
                continue
            home, away = league.teams[i], league.teams[j]
            lam_h, lam_a = league.expected_goals(home, away)
            # realised scoring in a full match runs a little above the pre-match
            # baseline (score-state and late-game effects); mirror that here.
            gh = int(rng.poisson(lam_h * 1.12))
            ga = int(rng.poisson(lam_a * 1.12))
            results.append((home.team_id, away.team_id, gh, ga))
    return results


def season_table(results: List[Tuple[str, str, int, int]]) -> List[dict]:
    table = {}
    for h, a, gh, ga in results:
        for tid in (h, a):
            table.setdefault(tid, {"team_id": tid, "P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Pts": 0})
        table[h]["P"] += 1
        table[a]["P"] += 1
        table[h]["GF"] += gh
        table[h]["GA"] += ga
        table[a]["GF"] += ga
        table[a]["GA"] += gh
        if gh > ga:
            table[h]["W"] += 1
            table[a]["L"] += 1
            table[h]["Pts"] += 3
        elif gh < ga:
            table[a]["W"] += 1
            table[h]["L"] += 1
            table[a]["Pts"] += 3
        else:
            table[h]["D"] += 1
            table[a]["D"] += 1
            table[h]["Pts"] += 1
            table[a]["Pts"] += 1
    return sorted(table.values(), key=lambda r: (-r["Pts"], -(r["GF"] - r["GA"]), -r["GF"]))
