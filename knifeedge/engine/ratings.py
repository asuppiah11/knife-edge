"""Team ratings fitted from historical (synthetic) results.

A Poisson goals model with attack and defence strengths per team, a home
advantage and an intercept, fitted by maximum likelihood. This is the
pre-match prior the live engine starts from; it is fitted on the synthetic
league's previous season, never on real data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np
from scipy.optimize import minimize


@dataclass
class Ratings:
    team_ids: List[str]
    attack: Dict[str, float]
    defence: Dict[str, float]
    home_advantage: float
    intercept: float
    n_matches: int

    def expected(self, home_id: str, away_id: str) -> tuple[float, float]:
        lam_h = float(np.exp(self.intercept + self.attack[home_id] + self.defence[away_id] + self.home_advantage))
        lam_a = float(np.exp(self.intercept + self.attack[away_id] + self.defence[home_id]))
        return lam_h, lam_a

    def to_json(self, path: Path) -> None:
        Path(path).write_text(json.dumps({"team_ids": self.team_ids, "attack": self.attack, "defence": self.defence, "home_advantage": self.home_advantage, "intercept": self.intercept, "n_matches": self.n_matches}, indent=2))

    @classmethod
    def from_json(cls, path: Path) -> "Ratings":
        d = json.loads(Path(path).read_text())
        return cls(d["team_ids"], d["attack"], d["defence"], d["home_advantage"], d["intercept"], d["n_matches"])


def fit_ratings(results: Sequence[tuple[str, str, int, int]], team_ids: Sequence[str] | None = None, ridge: float = 0.02) -> Ratings:
    """Fit from (home_id, away_id, home_goals, away_goals) rows."""
    if team_ids is None:
        team_ids = sorted({r[0] for r in results} | {r[1] for r in results})
    team_ids = list(team_ids)
    idx = {t: i for i, t in enumerate(team_ids)}
    n = len(team_ids)
    H = np.array([idx[r[0]] for r in results])
    A = np.array([idx[r[1]] for r in results])
    gh = np.array([r[2] for r in results], dtype=float)
    ga = np.array([r[3] for r in results], dtype=float)

    def unpack(theta):
        att = theta[:n]
        dfc = theta[n : 2 * n]
        home = theta[2 * n]
        icpt = theta[2 * n + 1]
        return att, dfc, home, icpt

    def nll(theta):
        att, dfc, home, icpt = unpack(theta)
        lh = icpt + att[H] + dfc[A] + home
        la = icpt + att[A] + dfc[H]
        ll = (gh * lh - np.exp(lh)).sum() + (ga * la - np.exp(la)).sum()
        pen = ridge * (att @ att + dfc @ dfc)
        return -ll + pen

    def grad(theta):
        att, dfc, home, icpt = unpack(theta)
        lh = icpt + att[H] + dfc[A] + home
        la = icpt + att[A] + dfc[H]
        rh = gh - np.exp(lh)
        ra = ga - np.exp(la)
        g = np.zeros_like(theta)
        np.add.at(g, H, -rh)  # d/d att[H]
        np.add.at(g, A, -ra)  # d/d att[A]
        np.add.at(g, n + A, -rh)  # d/d dfc[A]
        np.add.at(g, n + H, -ra)  # d/d dfc[H]
        g[2 * n] = -rh.sum()
        g[2 * n + 1] = -(rh.sum() + ra.sum())
        g[:n] += 2 * ridge * att
        g[n : 2 * n] += 2 * ridge * dfc
        return g

    theta0 = np.zeros(2 * n + 2)
    theta0[2 * n + 1] = np.log(max((gh.mean() + ga.mean()) / 2, 0.1))
    res = minimize(nll, theta0, jac=grad, method="L-BFGS-B")
    att, dfc, home, icpt = unpack(res.x)
    # identifiability: centre attack and defence, fold the shift into the intercept
    icpt = icpt + att.mean() + dfc.mean()
    att = att - att.mean()
    dfc = dfc - dfc.mean()
    return Ratings(team_ids, {t: float(att[i]) for t, i in idx.items()}, {t: float(dfc[i]) for t, i in idx.items()}, float(home), float(icpt), len(results))


def league_average_prior() -> tuple[float, float]:
    """Fallback prior when no ratings are available: typical home/away goals per 90."""
    return 1.55, 1.25
