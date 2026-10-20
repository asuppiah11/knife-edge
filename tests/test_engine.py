"""Engine: probabilities, Greeks signs, replay decomposition, ratings."""

import numpy as np
import pytest

from knifeedge.engine.greeks import compute_greeks
from knifeedge.engine.ratings import fit_ratings
from knifeedge.engine.replay import MatchReplay
from knifeedge.engine.state import MatchState
from knifeedge.engine.wp import outcome_probs
from knifeedge.sim import build_league, simulate_match
from knifeedge.sim.season import generate_season


def test_outcome_probs_sum_to_one():
    p = outcome_probs(1, 0, 0.8, 1.1)
    assert abs(p.p_home + p.p_draw + p.p_away - 1) < 1e-9


def test_outcome_probs_limits():
    almost_over = outcome_probs(1, 0, 0.001, 0.001)
    assert almost_over.p_home > 0.99
    level_long = outcome_probs(0, 0, 1.5, 1.5)
    assert abs(level_long.p_home - level_long.p_away) < 1e-9


def _state(home_goals=0, away_goals=0, elapsed=60.0, home_men=11, away_men=11):
    s = MatchState("H", "A", 1.5, 1.2, elapsed_min=elapsed, home_goals=home_goals, away_goals=away_goals, home_men=home_men, away_men=away_men)
    return s


def test_greek_signs_for_leader():
    g = compute_greeks(_state(1, 0, 70))
    assert g.delta_home_goal > 0 and g.delta_away_goal < 0
    assert g.theta_home > 0  # time works for the leader
    assert g.theta_away < 0
    assert g.vega_home < 0  # chaos hurts the leader
    assert g.vega_away > 0


def test_knife_edge_peaks_when_level_late():
    early = compute_greeks(_state(0, 0, 10))
    late = compute_greeks(_state(0, 0, 85))
    assert late.knife_edge > early.knife_edge


def test_red_card_lowers_probability():
    base = compute_greeks(_state(0, 0, 30))
    down = compute_greeks(_state(0, 0, 30, home_men=10))
    assert down.p_home < base.p_home


@pytest.fixture(scope="module")
def replay():
    sim = simulate_match(seed=42)
    return MatchReplay(sim.match_header(), sim.events, priors=(sim.lam_h90, sim.lam_a90)).run(), sim


def test_decomposition_adds_up(replay):
    rp, _ = replay
    for s in rp.snapshots:
        total = sum(s.decomposition.values())
        assert abs(total - s.swing_pts) < 1e-6


def test_final_probability_matches_result(replay):
    rp, sim = replay
    score = sim.match_header()["score"]
    f = rp.final
    if score["home"] > score["away"]:
        assert f["p_home"] > 0.95
    elif score["home"] < score["away"]:
        assert f["p_away"] > 0.95
    else:
        assert f["p_draw"] > 0.95


def test_goal_swing_attributed_to_score(replay):
    rp, _ = replay
    goals = [s for s in rp.snapshots if s.type == "shot" and s.outcome == "goal"]
    assert goals
    for g in goals:
        assert abs(g.decomposition["score"]) > 5
        assert abs(g.decomposition["momentum"]) < 1e-6


def test_non_goal_events_move_little(replay):
    rp, _ = replay
    quiet = [abs(s.swing_pts) for s in rp.snapshots if s.type not in ("shot", "card")]
    assert np.percentile(quiet, 99) < 2.0


def test_scenario_and_why(replay):
    rp, _ = replay
    top = rp.top_moments(1)[0]
    why = rp.why_it_moved(top["event_id"])
    assert why["evidence_event_ids"]
    sc = rp.scenario(60, home_goal=1)
    assert sc["swing_pts"] > 0


def test_ratings_recover_strengths():
    league = build_league(3)
    results = generate_season(league, seed=9)
    r = fit_ratings(results, [t.team_id for t in league.teams])
    true_att = np.array([t.attack for t in league.teams])
    fit_att = np.array([r.attack[t.team_id] for t in league.teams])
    assert np.corrcoef(true_att, fit_att)[0, 1] > 0.6
    assert 0.1 < r.home_advantage < 0.45
