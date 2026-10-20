"""Verifier and cue pipeline: grounding, fallback, schema, languages, fault injection."""

import json
from pathlib import Path

import jsonschema
import pytest

from knifeedge.agents.pipeline import CuePipeline, _parse_json_object
from knifeedge.agents.verifier import verify_cue
from knifeedge.engine.replay import MatchReplay
from knifeedge.sim import simulate_match

ROOT = Path(__file__).resolve().parents[1]
FACTS = {"player": "Arlo Brandt", "team": "Carrow Vale", "swing_pts": 14.2, "team_p_pct": 64.8, "xg": 0.57, "score_home": 1, "score_away": 0, "minute_label": "28'"}
NAMES = ["Arlo Brandt", "Carrow Vale", "Dunston Rovers", "CAR", "DUN"]


def test_verifier_passes_grounded_text():
    r = verify_cue("Arlo Brandt scores. CAR 1-0 DUN", "Swing of 14.2 points: Carrow Vale are now 64.8% to win at 28'.", FACTS, NAMES, [10], {10, 11})
    assert r.passed, r.rejections


def test_verifier_rejects_wrong_number():
    r = verify_cue("Arlo Brandt scores", "Swing of 18 points: Carrow Vale are now 64.8% to win.", FACTS, NAMES, [10], {10})
    assert not r.passed and any("numbers" in x for x in r.rejections)


def test_verifier_rejects_unknown_player():
    r = verify_cue("Marco Bellini scores", "Swing of 14.2 points.", FACTS, NAMES, [10], {10})
    assert not r.passed and any("unknown names" in x for x in r.rejections)


def test_verifier_rejects_betting_language():
    r = verify_cue("Arlo Brandt scores", "The odds have shifted: Carrow Vale 64.8% to win.", FACTS, NAMES, [10], {10})
    assert not r.passed and any("banned" in x for x in r.rejections)


def test_verifier_rejects_missing_evidence():
    r = verify_cue("Arlo Brandt scores", "Swing of 14.2 points.", FACTS, NAMES, [], {10})
    assert not r.passed
    r2 = verify_cue("Arlo Brandt scores", "Swing of 14.2 points.", FACTS, NAMES, [99], {10})
    assert not r2.passed


def test_verifier_rejects_wrong_minute_label():
    r = verify_cue("Arlo Brandt scores", "Swing of 14.2 points at 31'.", FACTS, NAMES, [10], {10})
    assert not r.passed and any("minute label" in x for x in r.rejections)


@pytest.fixture(scope="module")
def replay():
    sim = simulate_match(seed=42)
    return MatchReplay(sim.match_header(), sim.events, priors=(sim.lam_h90, sim.lam_a90)).run()


@pytest.mark.parametrize("audience,lang", [("casual", "en"), ("analyst", "en"), ("bench", "en"), ("casual", "es"), ("casual", "ta"), ("bench", "es"), ("analyst", "ta")])
def test_template_cues_verify_and_match_schema(replay, audience, lang):
    schema = json.loads((ROOT / "schemas" / "overlay_cue.schema.json").read_text())
    cues = CuePipeline(replay).run(audience=audience, lang=lang, max_cues=10)
    assert cues
    for c in cues:
        jsonschema.validate(c, schema)
        assert c["verifier"]["passed"], (c["headline"], c["verifier"]["rejections"])
        assert c["source"] == "template"
        assert c["t_out_s"] > c["t_in_s"]


def test_bench_prompts_are_limited(replay):
    cues = CuePipeline(replay).run(audience="bench", lang="en", max_cues=20)
    prompts = [c for c in cues if c["kind"] == "bench_prompt"]
    assert len(prompts) <= 6
    for p in prompts:
        assert p["confidence"] is not None and 0.5 <= p["confidence"] <= 0.9
        assert p["action"]


class _BadLLM:
    """Fault injection: returns a draft with a wrong number, then a grounded one."""

    def __init__(self):
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        facts = json.loads(user.split("FACTS (the only numbers you may use):\n")[1].split("\nALLOWED_NAMES")[0])
        if self.calls % 2 == 1:
            return json.dumps({"headline": "Big moment", "body": "That swung the match by 777 points."})
        # grounded retry: only numbers from facts
        swing = facts.get("swing_pts", facts.get("expected_pts", facts.get("knife_edge_pts", 0)))
        return json.dumps({"headline": "Big moment", "body": f"That moment was worth {swing} points."})


def test_llm_wrong_number_is_caught_and_retried(replay):
    llm = _BadLLM()
    cues = CuePipeline(replay, llm=llm).run(audience="casual", lang="en", max_cues=3)
    assert cues
    assert all(c["verifier"]["passed"] for c in cues)
    assert all(c["source"] in ("llm_retry", "template") for c in cues)


class _AlwaysWrongLLM:
    def complete(self, system, user):
        return json.dumps({"headline": "Odds have moved", "body": "Bet now: 777 points."})


def test_llm_persistent_failure_falls_back_to_template(replay):
    cues = CuePipeline(replay, llm=_AlwaysWrongLLM()).run(audience="casual", lang="en", max_cues=3)
    assert cues and all(c["source"] == "template" and c["verifier"]["passed"] for c in cues)


def test_parse_json_object_handles_fences():
    assert _parse_json_object('```json\n{"headline": "a", "body": "b"}\n```') == {"headline": "a", "body": "b"}
    with pytest.raises(ValueError):
        _parse_json_object("no json here")
