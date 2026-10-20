"""HTTP API and MCP endpoint smoke tests (template mode, no network)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knifeedge.api.app import create_app
from knifeedge.engine.ratings import fit_ratings
from knifeedge.sim import build_league, simulate_match
from knifeedge.sim.season import generate_season


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("matches")
    league = build_league()
    simulate_match(seed=42, league=league).write(root / "KE-000042")
    ratings = fit_ratings(generate_season(league), [t.team_id for t in league.teams])
    rp = root / "ratings.json"
    ratings.to_json(rp)
    app = create_app(root, rp)
    with TestClient(app) as c:
        yield c


def test_health_and_list(client):
    assert client.get("/health").json()["ok"]
    assert client.get("/matches").json()[0]["match_id"] == "KE-000042"


def test_greeks_and_moments(client):
    g = client.get("/matches/KE-000042/greeks", params={"minute": 60}).json()
    assert 0 <= g["greeks"]["p_home"] <= 100
    m = client.get("/matches/KE-000042/moments", params={"n": 3}).json()
    assert len(m) == 3
    why = client.get(f"/matches/KE-000042/why/{m[0]['event_id']}").json()
    assert "decomposition_pts" in why


def test_scenario_and_cues(client):
    sc = client.get("/matches/KE-000042/scenario", params={"minute": 60, "home_goal": 1}).json()
    assert sc["swing_pts"] > 0
    cues = client.get("/matches/KE-000042/cues", params={"audience": "casual", "lang": "ta", "max": 4}).json()
    assert cues and all(c["verifier"]["passed"] for c in cues)


def test_unknown_match_404(client):
    assert client.get("/matches/NOPE/greeks").status_code == 404


def test_stream_emits_events(client):
    n = 0
    with client.stream("GET", "/matches/KE-000042/stream", params={"speed": 1e6}) as r:
        for line in r.iter_lines():
            if line.startswith("event: match"):
                n += 1
            if n >= 3:
                break
    assert n == 3


def _last(r):
    data = [l[5:] for l in r.text.splitlines() if l.startswith("data:")]
    return json.loads(data[-1]) if data else r.json()


def test_mcp_tools_list_and_call(client):
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}, headers=h)
    assert r.status_code == 200
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=h)
    names = {t["name"] for t in _last(r)["result"]["tools"]}
    assert {"greeks_now", "why_it_moved", "top_moments", "theta_curve", "scenario"} <= names
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "greeks_now", "arguments": {"match_id": "KE-000042", "minute": 60}}}, headers=h)
    assert "greeks" in _last(r)["result"]["content"][0]["text"]
