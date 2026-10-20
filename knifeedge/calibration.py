"""Honest model evaluation against simulated outcomes.

Because the generator records the truth, we can measure how well the
engine's live probabilities are calibrated. Three models are compared:

* ``prematch``  - the pre-match probability frozen for the whole match (naive baseline)
* ``live``      - score, clock and cards, no evidence/momentum term
* ``live+mom``  - the full engine (score, clock, cards, momentum from chance quality and field tilt)

Metrics: multiclass Brier score, ranked probability score (RPS), expected
calibration error (ECE) on P(home win) in deciles, plus a reliability table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from .engine.greeks import probs_for
from .engine.ratings import Ratings, fit_ratings
from .engine.replay import MatchReplay
from .engine.state import MatchState
from .sim import SimConfig, build_league, simulate_match
from .sim.season import generate_season

SAMPLE_MINUTES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]


@dataclass
class ModelEval:
    name: str
    probs: List[List[float]] = field(default_factory=list)  # [p_home, p_draw, p_away]
    outcomes: List[int] = field(default_factory=list)  # 0 home, 1 draw, 2 away
    minutes: List[int] = field(default_factory=list)

    def arrays(self):
        P = np.array(self.probs)
        O = np.zeros_like(P)
        O[np.arange(len(self.outcomes)), self.outcomes] = 1.0
        return P, O

    def brier(self) -> float:
        P, O = self.arrays()
        return float(((P - O) ** 2).sum(axis=1).mean())

    def rps(self) -> float:
        P, O = self.arrays()
        cp = np.cumsum(P, axis=1)[:, :2]
        co = np.cumsum(O, axis=1)[:, :2]
        return float(((cp - co) ** 2).sum(axis=1).mean() / 2.0)

    def log_loss(self) -> float:
        P, O = self.arrays()
        return float(-(O * np.log(np.clip(P, 1e-9, 1))).sum(axis=1).mean())

    def reliability(self, n_bins: int = 10) -> List[dict]:
        P, O = self.arrays()
        p = P[:, 0]
        o = O[:, 0]
        edges = np.linspace(0, 1, n_bins + 1)
        rows = []
        for i in range(n_bins):
            m = (p >= edges[i]) & (p < edges[i + 1] if i < n_bins - 1 else p <= edges[i + 1])
            if m.sum() == 0:
                rows.append({"bin": f"{edges[i]:.1f}-{edges[i+1]:.1f}", "n": 0, "mean_pred": None, "observed": None})
            else:
                rows.append({"bin": f"{edges[i]:.1f}-{edges[i+1]:.1f}", "n": int(m.sum()), "mean_pred": round(float(p[m].mean()), 4), "observed": round(float(o[m].mean()), 4)})
        return rows

    def ece(self, n_bins: int = 10) -> float:
        rows = self.reliability(n_bins)
        n = sum(r["n"] for r in rows)
        return float(sum(r["n"] / n * abs(r["mean_pred"] - r["observed"]) for r in rows if r["n"] > 0))

    def by_minute(self) -> List[dict]:
        P, O = self.arrays()
        mins = np.array(self.minutes)
        out = []
        for m in sorted(set(self.minutes)):
            mask = mins == m
            out.append({"minute": int(m), "n": int(mask.sum()), "brier": round(float(((P[mask] - O[mask]) ** 2).sum(axis=1).mean()), 4)})
        return out


def _outcome(score_h: int, score_a: int) -> int:
    return 0 if score_h > score_a else (1 if score_h == score_a else 2)


def run_calibration(n_matches: int = 500, seed0: int = 10_000, league_seed: int = 7, out_dir: Optional[Path] = None, plot: bool = True) -> dict:
    league = build_league(league_seed)
    results = generate_season(league, seed=league_seed + 4)
    ratings = fit_ratings(results, [t.team_id for t in league.teams])
    evals = {k: ModelEval(k) for k in ("prematch", "live", "live+mom")}
    goals_per_match: List[int] = []
    for i in range(n_matches):
        sim = simulate_match(seed=seed0 + i, league=league, config=SimConfig(texture=False))
        header = sim.match_header()
        outcome = _outcome(header["score"]["home"], header["score"]["away"])
        goals_per_match.append(header["score"]["home"] + header["score"]["away"])
        priors = ratings.expected(sim.home.team_id, sim.away.team_id)
        rp_mom = MatchReplay(header, sim.events, priors=priors, momentum=True).run()
        rp_live = MatchReplay(header, sim.events, priors=priors, momentum=False).run()
        pre = MatchState(sim.home.team_id, sim.away.team_id, *priors)
        p_pre = probs_for(pre)
        for m in SAMPLE_MINUTES:
            for name, rp in (("live", rp_live), ("live+mom", rp_mom)):
                g = rp.greeks_at(float(m))
                evals[name].probs.append([g.p_home, g.p_draw, g.p_away])
                evals[name].outcomes.append(outcome)
                evals[name].minutes.append(m)
            evals["prematch"].probs.append([p_pre.p_home, p_pre.p_draw, p_pre.p_away])
            evals["prematch"].outcomes.append(outcome)
            evals["prematch"].minutes.append(m)
    report = {
        "n_matches": n_matches,
        "n_samples_per_model": len(evals["live"].probs),
        "sample_minutes": SAMPLE_MINUTES,
        "goals_per_match": round(float(np.mean(goals_per_match)), 3),
        "home_win_rate": round(float(np.mean([o == 0 for o in evals["live"].outcomes[:: len(SAMPLE_MINUTES)]])), 3),
        "draw_rate": round(float(np.mean([o == 1 for o in evals["live"].outcomes[:: len(SAMPLE_MINUTES)]])), 3),
        "models": {},
        "ratings": {"home_advantage": round(ratings.home_advantage, 3), "intercept": round(ratings.intercept, 3), "n_matches": ratings.n_matches},
    }
    for name, ev in evals.items():
        report["models"][name] = {"brier": round(ev.brier(), 4), "rps": round(ev.rps(), 4), "log_loss": round(ev.log_loss(), 4), "ece_home": round(ev.ece(), 4), "reliability_home": ev.reliability(), "brier_by_minute": ev.by_minute()}
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "calibration.json").write_text(json.dumps(report, indent=2))
        (out_dir / "model-report.md").write_text(render_report_md(report))
        if plot:
            try:
                plot_reliability(report, out_dir / "reliability.png")
                report["plot"] = str(out_dir / "reliability.png")
            except Exception as exc:  # matplotlib is an optional dev dependency
                report["plot_error"] = repr(exc)
    return report


def render_report_md(report: dict) -> str:
    lines = [
        "# Model report: live win probability and Greeks",
        "",
        f"Evaluated on **{report['n_matches']} simulated matches** (fast mode, seeds from 10000), "
        f"sampling the model at minutes {report['sample_minutes']} - {report['n_samples_per_model']} samples per model. "
        f"Pre-match ratings were fitted on a separate synthetic season of {report['ratings']['n_matches']} results (fitted home advantage {report['ratings']['home_advantage']}).",
        "",
        f"Realism check: {report['goals_per_match']} goals per match; home win rate {report['home_win_rate']}; draw rate {report['draw_rate']}.",
        "",
        "## Headline metrics (lower is better)",
        "",
        "| Model | Brier (3-way) | RPS | Log loss | ECE P(home) |",
        "|---|---|---|---|---|",
    ]
    for name, m in report["models"].items():
        lines.append(f"| {name} | {m['brier']:.4f} | {m['rps']:.4f} | {m['log_loss']:.4f} | {m['ece_home']:.4f} |")
    lines += ["", "`prematch` freezes the pre-match probability; `live` uses score, clock and cards; `live+mom` adds the momentum/evidence term (age-weighted recent xG and field tilt).", "", "## Reliability of P(home win), full engine", "", "| Predicted bin | n | Mean predicted | Observed |", "|---|---|---|---|"]
    for r in report["models"]["live+mom"]["reliability_home"]:
        if r["n"]:
            lines.append(f"| {r['bin']} | {r['n']} | {r['mean_pred']:.3f} | {r['observed']:.3f} |")
    lines += ["", "## Brier by minute, full engine", "", "| Minute | n | Brier |", "|---|---|---|"]
    for r in report["models"]["live+mom"]["brier_by_minute"]:
        lines.append(f"| {r['minute']} | {r['n']} | {r['brier']:.4f} |")
    lines += ["", "![Reliability diagram](reliability.png)", "", "_Generated by `knife-edge calibrate`. All matches are synthetic; the generator's hidden truth lets us score the engine honestly, but it also means these numbers describe the synthetic league, not real football._"]
    return "\n".join(lines) + "\n"


def plot_reliability(report: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), dpi=150)
    ax = axes[0]
    ax.plot([0, 1], [0, 1], color="#9aa0a6", linewidth=1, linestyle="--", label="perfect")
    colours = {"prematch": "#b0b7c3", "live": "#5b8def", "live+mom": "#1b2a4a"}
    for name, m in report["models"].items():
        xs = [r["mean_pred"] for r in m["reliability_home"] if r["n"]]
        ys = [r["observed"] for r in m["reliability_home"] if r["n"]]
        ax.plot(xs, ys, marker="o", markersize=4, linewidth=1.5, color=colours[name], label=f"{name} (ECE {m['ece_home']:.3f})")
    ax.set_xlabel("Predicted P(home win)")
    ax.set_ylabel("Observed frequency")
    ax.set_title("Reliability")
    ax.legend(frameon=False, fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.spines[["top", "right"]].set_visible(False)
    ax = axes[1]
    for name, m in report["models"].items():
        xs = [r["minute"] for r in m["brier_by_minute"]]
        ys = [r["brier"] for r in m["brier_by_minute"]]
        ax.plot(xs, ys, marker="o", markersize=4, linewidth=1.5, color=colours[name], label=name)
    ax.set_xlabel("Minute sampled")
    ax.set_ylabel("Brier score (3-way)")
    ax.set_title("Accuracy through the match")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
