"""FastAPI service exposing the engine, the cue pipeline and a live replay stream.

    knife-edge serve --matches data/matches --ratings data/ratings.json
    open http://localhost:8000/

Endpoints
---------
GET  /health
GET  /matches
GET  /matches/{id}                      header + summary
GET  /matches/{id}/minutes              per-minute Greeks for charts
GET  /matches/{id}/greeks?minute=       Greeks + intensity breakdown
GET  /matches/{id}/why/{event_id}       swing decomposition + evidence
GET  /matches/{id}/moments?n=&kind=
GET  /matches/{id}/theta
GET  /matches/{id}/scenario?minute=&home_goal=&away_goal=&red_home=&red_away=&chaos=
GET  /matches/{id}/cues?audience=&lang=&max=&team=
GET  /matches/{id}/events?after=&limit=
GET  /matches/{id}/stream?speed=        SSE replay: one message per event, in match time / speed
GET  /schemas/{name}
POST /admin/refresh
MCP  /mcp                               streamable-HTTP MCP endpoint (same tools as mcp_server)
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..agents.pipeline import CuePipeline, FaultInjectingLLM
from . import mcp_server
from .store import MatchStore

ROOT = Path(__file__).resolve().parents[2]


def create_app(matches_dir: Path = Path("data/matches"), ratings_path: Optional[Path] = None, llm=None) -> FastAPI:
    store = MatchStore(matches_dir, ratings_path)
    mcp_server._store = store
    mcp = None
    mcp_error = None
    try:
        mcp = mcp_server.build_mcp()
    except Exception as exc:  # mcp is optional
        mcp_error = repr(exc)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if mcp is not None:
            async with mcp.session_manager.run():
                yield
        else:
            yield

    app = FastAPI(title="Knife-Edge", version="0.1.0", description="Live football match intelligence measured in sensitivities. All data is synthetic.", lifespan=lifespan)
    app.state.mcp_error = mcp_error
    app.state.store = store
    app.state.llm = llm

    def rp(match_id: str):
        try:
            return store.replay(match_id)
        except KeyError:
            raise HTTPException(404, f"unknown match {match_id}")

    @app.get("/health")
    def health():
        return {"ok": True, "matches": len(store.list()), "llm": "foundry" if llm else "template"}

    @app.get("/matches")
    def matches():
        return store.list()

    @app.get("/matches/{match_id}")
    def match(match_id: str):
        r = rp(match_id)
        return {"header": {k: v for k, v in store.header(match_id).items() if not k.startswith("_")}, "summary": r.summary()}

    @app.get("/matches/{match_id}/minutes")
    def minutes(match_id: str):
        return [m.__dict__ for m in rp(match_id).minutes]

    @app.get("/matches/{match_id}/greeks")
    def greeks(match_id: str, minute: Optional[float] = None):
        return rp(match_id).greeks_now(minute)

    @app.get("/matches/{match_id}/why/{event_id}")
    def why(match_id: str, event_id: int):
        try:
            return rp(match_id).why_it_moved(event_id)
        except KeyError:
            raise HTTPException(404, f"unknown event {event_id}")

    @app.get("/matches/{match_id}/moments")
    def moments(match_id: str, n: int = 5, kind: str = "realised"):
        return rp(match_id).top_moments(n, kind)

    @app.get("/matches/{match_id}/theta")
    def theta(match_id: str):
        return rp(match_id).theta_curve()

    @app.get("/matches/{match_id}/scenario")
    def scenario(match_id: str, minute: float, home_goal: int = 0, away_goal: int = 0, red_home: int = 0, red_away: int = 0, chaos: float = 1.0):
        return rp(match_id).scenario(minute, home_goal, away_goal, red_home, red_away, chaos)

    @app.get("/matches/{match_id}/cues")
    def cues(match_id: str, audience: str = "casual", lang: str = "en", max: int = Query(12, alias="max"), team: Optional[str] = None, player: Optional[str] = None, inject: int = 0):
        """inject=1 swaps in a fault-injecting model so the Verifier's rejection and the template fallback can be demonstrated."""
        chosen = FaultInjectingLLM() if inject else llm
        pipe = CuePipeline(rp(match_id), llm=chosen)
        return pipe.run(audience=audience, lang=lang, max_cues=max, bench_team_id=team, player_id=player)

    @app.get("/matches/{match_id}/events")
    def events(match_id: str, after: int = 0, limit: int = 5000):
        r = rp(match_id)
        out = [e for e in r.events if e["event_id"] > after][:limit]
        return out

    @app.get("/matches/{match_id}/timeline")
    def timeline(match_id: str):
        """Compact per-event engine output for client-side playback and scrubbing."""
        r = rp(match_id)
        keep = ("knife_edge", "theta_home", "theta_away", "vega_home", "vega_away", "next_goal_swing_home", "next_goal_swing_away", "delta_home_goal", "delta_away_goal")
        out = []
        for s in r.snapshots:
            out.append({
                "e": s.event_id, "t": round(s.clock_min * 60, 1), "l": s.label,
                "p": [round(s.p_home, 4), round(s.p_draw, 4), round(s.p_away, 4)],
                "sw": round(s.swing_pts, 2), "d": {k: round(v, 2) for k, v in s.decomposition.items()},
                "sc": [s.score_home, s.score_away], "men": [s.men_home, s.men_away],
                "g": {k: s.greeks[k] for k in keep},
                "xs": round(s.expected_swing_pts, 2) if s.expected_swing_pts is not None else None,
            })
        return out

    @app.get("/matches/{match_id}/stream")
    async def stream(match_id: str, speed: float = 60.0, start_min: float = 0.0):
        """Server-sent events: replays the match in real time divided by `speed` (60 = a match in ~95 s)."""
        r = rp(match_id)
        by_id = {s.event_id: s for s in r.snapshots}

        async def gen():
            last_clock = start_min * 60.0
            yield f"event: header\ndata: {json.dumps({k: v for k, v in store.header(match_id).items() if not k.startswith('_')})}\n\n"
            for ev in r.events:
                if ev["clock_s"] < start_min * 60.0:
                    continue
                wait = max(0.0, (ev["clock_s"] - last_clock) / max(speed, 1e-6))
                if wait > 0:
                    await asyncio.sleep(min(wait, 5.0))
                last_clock = ev["clock_s"]
                snap = by_id.get(ev["event_id"])
                payload = {"event": ev, "snapshot": snap.as_dict() if snap else None}
                yield f"event: match\ndata: {json.dumps(payload)}\n\n"
            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/schemas/{name}")
    def schema(name: str):
        path = ROOT / "schemas" / f"{name}.schema.json"
        if not path.exists():
            raise HTTPException(404, "unknown schema")
        return FileResponse(path)

    @app.post("/admin/refresh")
    def refresh():
        store.refresh()
        return {"matches": len(store.list())}

    # MCP (streamable HTTP) mounted alongside the REST API at /mcp
    if mcp is not None:
        try:  # mcp >= 2.0: path, stateless mode and host policy are arguments
            from mcp.server.transport_security import TransportSecuritySettings

            # The service sits behind the Container Apps ingress, so the Host header is the public FQDN.
            # Allow the hosts listed in KNIFE_EDGE_ALLOWED_HOSTS (comma separated, "*" = any) plus localhost.
            allowed = [h.strip() for h in os.environ.get("KNIFE_EDGE_ALLOWED_HOSTS", "*").split(",") if h.strip()]
            security = TransportSecuritySettings(enable_dns_rebinding_protection="*" not in allowed, allowed_hosts=[h for h in allowed if h != "*"] + ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"])
            mcp_app = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, transport_security=security)
        except TypeError:  # mcp 1.x
            mcp.settings.streamable_http_path = "/"
            mcp_app = mcp.streamable_http_app()
        app.mount("/mcp", mcp_app)

    web = ROOT / "web"
    if web.exists():
        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")
    return app


app = create_app(Path(os.environ.get("KNIFE_EDGE_MATCHES", "data/matches")), Path(os.environ.get("KNIFE_EDGE_RATINGS", "data/ratings.json")))
