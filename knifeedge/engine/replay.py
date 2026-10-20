"""Replay an event log through the engine, event by event.

For every event we record the outcome probabilities after it, the swing it
caused and a decomposition of that swing into time decay, momentum
(evidence), discipline and score. This is what the agents narrate and what
the Verifier checks against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .greeks import Greeks, compute_greeks, probs_for
from .state import MatchState
from .wp import outcome_probs
from .ratings import league_average_prior

FINAL_THIRD_X = 70.0


def minute_label(period: int, minute: int) -> str:
    if period == 1 and minute >= 45:
        return f"45+{minute - 44}'"
    if period == 2 and minute >= 90:
        return f"90+{minute - 89}'"
    return f"{minute + 1}'"


@dataclass
class EventSnapshot:
    event_id: int
    type: str
    team_id: str
    period: int
    minute: int
    label: str
    clock_min: float
    p_home: float
    p_draw: float
    p_away: float
    swing_pts: float  # change in P(home win), in points
    decomposition: Dict[str, float]
    score_home: int
    score_away: int
    men_home: int
    men_away: int
    greeks: Dict[str, float]  # points, after the event
    expected_swing_pts: Optional[float] = None  # shots only, before the outcome
    xg: Optional[float] = None
    outcome: Optional[str] = None
    player_id: Optional[str] = None

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        for k in ("p_home", "p_draw", "p_away"):
            d[k] = round(d[k], 4)
        d["swing_pts"] = round(self.swing_pts, 2)
        d["clock_min"] = round(self.clock_min, 2)
        d["decomposition"] = {k: round(v, 2) for k, v in self.decomposition.items()}
        if self.expected_swing_pts is not None:
            d["expected_swing_pts"] = round(self.expected_swing_pts, 2)
        return d


@dataclass
class MinuteSnapshot:
    elapsed_min: int
    period: int
    label: str
    score: List[int]
    greeks: Dict[str, float]
    intensity_home: dict
    intensity_away: dict


class MatchReplay:
    def __init__(self, header: dict, events: Iterable[dict], priors: Optional[tuple[float, float]] = None, momentum: bool = True):
        self.header = header
        self.events: List[dict] = list(events)
        self.home_id = header["home"]["team_id"]
        self.away_id = header["away"]["team_id"]
        lam_h, lam_a = priors if priors else league_average_prior()
        self.priors = (lam_h, lam_a)
        self.state = MatchState(self.home_id, self.away_id, lam_h, lam_a, momentum_on=momentum)
        self.snapshots: List[EventSnapshot] = []
        self.minutes: List[MinuteSnapshot] = []
        self.states_by_minute: Dict[int, MatchState] = {}
        self._by_id: Dict[int, EventSnapshot] = {}
        self._events_by_id: Dict[int, dict] = {e["event_id"]: e for e in self.events}
        self.players: Dict[str, dict] = {}
        for tid, lst in header.get("lineups", {}).items():
            for p in lst:
                self.players[p["player_id"]] = {**p, "team_id": tid}

    # ------------------------------------------------------------------ run
    def run(self) -> "MatchReplay":
        s = self.state
        p_prev = probs_for(s)
        last_minute_recorded = -1
        self.pre_match = p_prev.as_dict()
        for ev in self.events:
            clock_min = ev["clock_s"] / 60.0
            etype = ev["type"]
            tid = ev["team_id"]
            # 1) time decay
            s.elapsed_min = clock_min
            p_time = probs_for(s)
            # 2) evidence / momentum
            expected_swing = None
            xg = None
            if etype == "shot":
                xg = float(ev["shot"]["xg"])
                g_before = compute_greeks(s)
                d = g_before.delta_home_goal if tid == self.home_id else g_before.delta_away_goal
                expected_swing = 100 * xg * d
                if ev.get("outcome") != "goal":
                    # a goal is fully reflected in the score; only non-scoring chances count as momentum evidence
                    s.add_shot(tid, clock_min, xg, ev["event_id"])
            if etype in ("pass", "carry", "shot") and ev.get("x") is not None:
                s.add_touch(tid, clock_min, float(ev["x"]) >= FINAL_THIRD_X, ev["event_id"])
            p_mom = probs_for(s)
            # 3) discipline
            if etype == "card" and ev.get("card", {}).get("colour") in ("red", "second_yellow"):
                if tid == self.home_id:
                    s.home_men -= 1
                else:
                    s.away_men -= 1
            p_disc = probs_for(s)
            # 4) score
            if etype == "shot" and ev.get("outcome") == "goal":
                if tid == self.home_id:
                    s.home_goals += 1
                else:
                    s.away_goals += 1
            p_new = probs_for(s)
            decomposition = {
                "time": 100 * (p_time.p_home - p_prev.p_home),
                "momentum": 100 * (p_mom.p_home - p_time.p_home),
                "discipline": 100 * (p_disc.p_home - p_mom.p_home),
                "score": 100 * (p_new.p_home - p_disc.p_home),
            }
            g_after = compute_greeks(s)
            snap = EventSnapshot(
                event_id=ev["event_id"], type=etype, team_id=tid, period=ev["period"], minute=ev["minute"],
                label=minute_label(ev["period"], ev["minute"]), clock_min=clock_min,
                p_home=p_new.p_home, p_draw=p_new.p_draw, p_away=p_new.p_away,
                swing_pts=100 * (p_new.p_home - p_prev.p_home), decomposition=decomposition,
                score_home=s.home_goals, score_away=s.away_goals, men_home=s.home_men, men_away=s.away_men,
                greeks=g_after.points(),
                expected_swing_pts=expected_swing, xg=xg, outcome=ev.get("outcome"), player_id=ev.get("player_id"),
            )
            self.snapshots.append(snap)
            self._by_id[snap.event_id] = snap
            # minute series (first event at or after each whole elapsed minute)
            m = int(clock_min)
            if m > last_minute_recorded:
                last_minute_recorded = m
                self.minutes.append(MinuteSnapshot(m, ev["period"], minute_label(ev["period"], ev["minute"]), [s.home_goals, s.away_goals], g_after.points(), s.intensity(self.home_id).as_dict(), s.intensity(self.away_id).as_dict()))
                self.states_by_minute[m] = s.copy()
            p_prev = p_new
        self.final = p_prev.as_dict()
        return self

    # --------------------------------------------------------------- queries
    def greeks_at(self, elapsed_min: float) -> Greeks:
        st = self._state_at(elapsed_min)
        return compute_greeks(st)

    def _state_at(self, elapsed_min: float) -> MatchState:
        keys = [k for k in self.states_by_minute if k <= int(elapsed_min)]
        if not keys:
            st = MatchState(self.home_id, self.away_id, *self.priors, momentum_on=self.state.momentum_on)
            st.elapsed_min = max(0.0, elapsed_min)
            return st
        st = self.states_by_minute[max(keys)].copy()
        st.elapsed_min = max(st.elapsed_min, elapsed_min)
        return st

    def greeks_now(self, elapsed_min: Optional[float] = None) -> dict:
        em = self.snapshots[-1].clock_min if elapsed_min is None else elapsed_min
        st = self._state_at(em)
        g = compute_greeks(st)
        return {
            "elapsed_min": round(em, 2),
            "score": [st.home_goals, st.away_goals],
            "men": [st.home_men, st.away_men],
            "greeks": g.points(),
            "intensity": {"home": st.intensity(self.home_id).as_dict(), "away": st.intensity(self.away_id).as_dict()},
            "reading": self._reading(g, st),
        }

    def _reading(self, g: Greeks, st: MatchState) -> dict:
        """Plain-language tags derived from thresholds (used by templates and the UI)."""
        k = 100 * g.knife_edge
        fragility = "knife-edge" if k >= 30 else ("fragile" if k >= 20 else ("settled" if k >= 10 else "decided"))
        lead = st.home_goals - st.away_goals
        leader = self.home_id if lead > 0 else (self.away_id if lead < 0 else None)
        theta_leader = (100 * g.theta_home) if leader == self.home_id else ((100 * g.theta_away) if leader == self.away_id else 0.0)
        return {"fragility": fragility, "leader": leader, "theta_leader_pts_per_min": round(theta_leader, 2), "chaos_favours": self.home_id if g.vega_home > 0 else self.away_id}

    def why_it_moved(self, event_id: int) -> dict:
        snap = self._by_id[event_id]
        ev = self._events_by_id[event_id]
        st = self._state_at(snap.clock_min)
        evidence = [event_id]
        evidence += st.recent_shot_ids(self.home_id) + st.recent_shot_ids(self.away_id)
        evidence = sorted(set(evidence))
        return {
            "event": ev,
            "snapshot": snap.as_dict(),
            "decomposition_pts": {k: round(v, 2) for k, v in snap.decomposition.items()},
            "intensity_after": {"home": st.intensity(self.home_id).as_dict(), "away": st.intensity(self.away_id).as_dict()},
            "evidence_event_ids": evidence,
            "player": self.players.get(snap.player_id or "", None),
        }

    def top_moments(self, n: int = 5, kind: str = "realised") -> List[dict]:
        """Biggest moments. kind='realised' ranks by |swing|; 'expected' ranks shots by |xG × delta|."""
        if kind == "expected":
            cands = [s for s in self.snapshots if s.expected_swing_pts is not None]
            cands.sort(key=lambda s: -abs(s.expected_swing_pts or 0.0))
        else:
            cands = sorted(self.snapshots, key=lambda s: -abs(s.swing_pts))
        out = []
        for s in cands[:n]:
            d = s.as_dict()
            d["player"] = self.players.get(s.player_id or "", None)
            d["event"] = self._events_by_id[s.event_id]
            out.append(d)
        return out

    def theta_curve(self) -> List[dict]:
        return [{"elapsed_min": m.elapsed_min, "label": m.label, "score": m.score, "theta_home": m.greeks["theta_home"], "theta_away": m.greeks["theta_away"], "p_home": m.greeks["p_home"], "knife_edge": m.greeks["knife_edge"]} for m in self.minutes]

    def scenario(self, elapsed_min: float, home_goal: int = 0, away_goal: int = 0, red_home: int = 0, red_away: int = 0, chaos: float = 1.0) -> dict:
        st = self._state_at(elapsed_min)
        base = compute_greeks(st)
        hyp = st.copy()
        hyp.home_goals += home_goal
        hyp.away_goals += away_goal
        hyp.home_men -= red_home
        hyp.away_men -= red_away
        ih, ia = hyp.intensity(self.home_id, chaos=chaos), hyp.intensity(self.away_id, chaos=chaos)
        p = outcome_probs(hyp.home_goals, hyp.away_goals, ih.lam_remaining, ia.lam_remaining)
        g = compute_greeks(hyp)
        return {
            "elapsed_min": round(elapsed_min, 2),
            "base": base.points(),
            "scenario": {"home_goal": home_goal, "away_goal": away_goal, "red_home": red_home, "red_away": red_away, "chaos": chaos},
            "result": {**p.as_dict(), "greeks": g.points()},
            "swing_pts": round(100 * (p.p_home - base.p_home), 2),
        }

    # --------------------------------------------------------------- summary
    def team_stats(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for tid in (self.home_id, self.away_id):
            opp = self.away_id if tid == self.home_id else self.home_id
            evs = [e for e in self.events if e["team_id"] == tid]
            shots = [e for e in evs if e["type"] == "shot"]
            passes = [e for e in evs if e["type"] == "pass"]
            completed = [e for e in passes if e.get("outcome") == "success"]
            pressures = [e for e in evs if e["type"] == "pressure"]
            # PPDA counts tackles, interceptions and fouls in the opponent's build-up zone (not pressures)
            def_actions_high = [e for e in evs if e["type"] in ("tackle", "interception", "foul") and (e.get("x") or 0) >= 42.0]
            opp_build_passes = [e for e in self.events if e["team_id"] == opp and e["type"] == "pass" and (e.get("x") or 0) < 63.0]
            carries = [e for e in evs if e["type"] == "carry"]
            touches_f3 = [e for e in evs if e["type"] in ("pass", "carry", "shot") and (e.get("x") or 0) >= FINAL_THIRD_X]
            opp_touches_f3 = [e for e in self.events if e["team_id"] == opp and e["type"] in ("pass", "carry", "shot") and (e.get("x") or 0) >= FINAL_THIRD_X]
            out[tid] = {
                "goals": sum(1 for s in shots if s.get("outcome") == "goal"),
                "shots": len(shots),
                "shots_on_target": sum(1 for s in shots if s.get("outcome") in ("goal", "saved")),
                "xg": round(sum(float(s["shot"]["xg"]) for s in shots), 2),
                "passes": len(passes),
                "pass_completion_pct": round(100 * len(completed) / max(len(passes), 1), 1),
                "progressive_passes": sum(1 for p in passes if p.get("pass", {}).get("progressive")),
                "pressures": len(pressures),
                "ppda": round(len(opp_build_passes) / max(len(def_actions_high), 1), 1),
                "field_tilt_pct": round(100 * len(touches_f3) / max(len(touches_f3) + len(opp_touches_f3), 1), 1),
                "carries": len(carries),
                "sprints": sum(1 for c in carries if c.get("carry", {}).get("sprint")),
                "distance_carried_m": round(sum(float(c.get("carry", {}).get("distance_m", 0)) for c in carries), 0),
            }
        return out

    def player_physical(self, top_n: int = 5) -> dict:
        """Player tagging from carries: distance carried, top speed, sprint count."""
        agg: Dict[str, dict] = {}
        for e in self.events:
            if e["type"] != "carry" or not e.get("player_id"):
                continue
            c = e.get("carry", {})
            a = agg.setdefault(e["player_id"], {"player_id": e["player_id"], "team_id": e["team_id"], "distance_m": 0.0, "top_speed_ms": 0.0, "sprints": 0, "name": self.players.get(e["player_id"], {}).get("name")})
            a["distance_m"] += float(c.get("distance_m", 0.0))
            a["top_speed_ms"] = max(a["top_speed_ms"], float(c.get("speed_ms", 0.0)))
            a["sprints"] += 1 if c.get("sprint") else 0
        rows = list(agg.values())
        for r in rows:
            r["distance_m"] = round(r["distance_m"], 0)
            r["top_speed_kmh"] = round(3.6 * r["top_speed_ms"], 1)
            r["top_speed_ms"] = round(r["top_speed_ms"], 2)
        return {
            "most_distance": sorted(rows, key=lambda r: -r["distance_m"])[:top_n],
            "fastest": sorted(rows, key=lambda r: -r["top_speed_ms"])[:top_n],
            "most_sprints": sorted(rows, key=lambda r: -r["sprints"])[:top_n],
        }

    def summary(self) -> dict:
        most_fragile = max(self.minutes, key=lambda m: m.greeks["knife_edge"]) if self.minutes else None
        return {
            "match_id": self.header["match_id"],
            "home": self.header["home"],
            "away": self.header["away"],
            "score": self.header.get("score"),
            "pre_match": self.pre_match,
            "final": self.final,
            "biggest_moments": self.top_moments(5),
            "biggest_expected_moments": self.top_moments(5, kind="expected"),
            "most_fragile_minute": {"label": most_fragile.label, "knife_edge": most_fragile.greeks["knife_edge"], "score": most_fragile.score} if most_fragile else None,
            "team_stats": self.team_stats(),
            "player_physical": self.player_physical(),
        }

    # ---------------------------------------------------------------- output
    def write(self, out_dir: Path) -> None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        compact = []
        for snap in self.snapshots:
            d = snap.as_dict()
            d.pop("greeks", None)
            compact.append(d)
        (out_dir / "timeline.json").write_text(json.dumps(compact))
        (out_dir / "minutes.json").write_text(json.dumps([m.__dict__ for m in self.minutes], indent=1))
        (out_dir / "summary.json").write_text(json.dumps(self.summary(), indent=2))


def load_match(match_dir: Path) -> tuple[dict, List[dict]]:
    match_dir = Path(match_dir)
    header = json.loads((match_dir / "match.json").read_text())
    events = [json.loads(line) for line in (match_dir / "events.jsonl").read_text().splitlines() if line.strip()]
    return header, events


def replay_match(match_dir: Path, priors: Optional[tuple[float, float]] = None, momentum: bool = True) -> MatchReplay:
    header, events = load_match(match_dir)
    return MatchReplay(header, events, priors=priors, momentum=momentum).run()
