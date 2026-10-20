"""Synthetic generator: determinism, schema validity, realism ranges."""

import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from knifeedge.sim import SimConfig, build_league, simulate_match

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def match():
    return simulate_match(seed=42)


def test_deterministic():
    a = simulate_match(seed=5)
    b = simulate_match(seed=5)
    assert [e["type"] for e in a.events] == [e["type"] for e in b.events]
    assert a.match_header()["score"] == b.match_header()["score"]
    assert json.dumps(a.truth(), sort_keys=True) == json.dumps(b.truth(), sort_keys=True)


def test_events_match_schema(match):
    schema = json.loads((ROOT / "schemas" / "event.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for ev in match.events[:600]:
        validator.validate(ev)


def test_header_matches_schema(match):
    schema = json.loads((ROOT / "schemas" / "match.schema.json").read_text())
    jsonschema.validate(match.match_header(), schema)


def test_realism_ranges():
    goals, shots, comp, n_events, pressures = [], [], [], [], []
    for seed in range(300, 324):
        sim = simulate_match(seed=seed)
        sh = [e for e in sim.events if e["type"] == "shot"]
        ps = [e for e in sim.events if e["type"] == "pass"]
        goals.append(sum(sim.match_header()["score"].values()))
        shots.append(len(sh))
        comp.append(sum(1 for p in ps if p["outcome"] == "success") / len(ps))
        n_events.append(len(sim.events))
        pressures.append(sum(1 for e in sim.events if e["type"] == "pressure"))
    assert 1.8 <= np.mean(goals) <= 4.0
    assert 16 <= np.mean(shots) <= 34
    assert 0.76 <= np.mean(comp) <= 0.90
    assert 1400 <= np.mean(n_events) <= 3200
    assert 100 <= np.mean(pressures) <= 500


def test_goals_consistent_with_hidden_truth():
    """Realised goals should track the hidden xG the generator drew them from."""
    hidden, goals = 0.0, 0
    for seed in range(400, 460):
        sim = simulate_match(seed=seed, config=SimConfig(texture=False))
        shots = {e["event_id"]: e for e in sim.events if e["type"] == "shot"}
        for s in sim.truth()["shots"]:
            hidden += s["hidden_xg"]
            goals += shots[s["event_id"]]["outcome"] == "goal"
    assert abs(goals - hidden) / hidden < 0.15


def test_coordinates_on_pitch(match):
    for ev in match.events:
        for k in ("x", "end_x"):
            if ev.get(k) is not None:
                assert 0 <= ev[k] <= 105
        for k in ("y", "end_y"):
            if ev.get(k) is not None:
                assert 0 <= ev[k] <= 68


def test_clock_monotone(match):
    clocks = [e["clock_s"] for e in match.events]
    assert all(b >= a for a, b in zip(clocks, clocks[1:]))


def test_league_is_fictional():
    league = build_league()
    names = {t.name for t in league.teams}
    assert len(names) == 20
    for real in ("Arsenal", "Chelsea", "Liverpool", "Manchester", "Tottenham", "Everton", "Newcastle"):
        assert not any(real.lower() in n.lower() for n in names)
