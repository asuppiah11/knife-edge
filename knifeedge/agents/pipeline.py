"""Cue pipeline: Quant -> Tactician -> Narrator -> Localiser -> Verifier.

Roles
-----
Quant       picks the moments worth talking about from the replay (realised
            swings, big chances, fragility peaks, theta and vega readings).
Tactician   adds tactical context (field tilt, pressure, momentum) and, for
            the bench audience, turns readings into at most three prompts a
            half, each with an action, evidence and a confidence level.
Narrator    writes the words. In LLM mode a Foundry model drafts from the
            facts; in template mode the templates are used directly.
Localiser   produces Spanish or Tamil. In LLM mode the model translates with
            numbers pinned; in template mode the localised templates are used.
Verifier    deterministic grounding: every number, name and evidence id must
            check out, or the draft is retried once and then replaced by the
            template.

The LLM is injected (``llm.complete(system, user) -> str``) so the same
pipeline runs offline, in tests, and on Foundry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol

from ..engine.replay import MatchReplay
from . import roles
from .templates import OUTCOME_WORDS, render
from .verifier import VerifierResult, verify_cue

KNIFE_EDGE_THRESHOLD_PTS = 30.0
CUE_DURATION_S = 12.0
_BIGGEST = {True: "biggest", False: "big"}
RANK_PHRASES = {
    "en": ("Nothing since kick-off has carried more.", "One of the three biggest chances of the match."),
    "es": ("Nada desde el inicio ha pesado tanto.", "Una de las tres mayores ocasiones del partido."),
    "ta": ("ஆட்டம் தொடங்கியதிலிருந்து இதைவிட பெரிய வாய்ப்பு இல்லை.", "ஆட்டத்தின் மூன்று பெரிய வாய்ப்புகளில் ஒன்று."),
}
BIGGEST_PHRASES = {
    "en": {"biggest": "That is the biggest single moment of the match so far.", "big": "One of the big moments of the match."},
    "es": {"biggest": "El momento más grande del partido hasta ahora.", "big": "Uno de los grandes momentos del partido."},
    "ta": {"biggest": "இதுவரை ஆட்டத்தின் மிகப்பெரிய தருணம்.", "big": "ஆட்டத்தின் பெரிய தருணங்களில் ஒன்று."},
}


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str:  # pragma: no cover - protocol
        ...


@dataclass
class Moment:
    kind: str
    clock_min: float
    period: int
    label: str
    facts: Dict
    evidence: List[int]
    priority: int
    greeks: Dict
    confidence: Optional[float] = None
    action: Optional[str] = None


class CuePipeline:
    def __init__(self, replay: MatchReplay, llm: Optional[LLM] = None):
        self.rp = replay
        self.llm = llm
        self.header = replay.header
        self.home = self.header["home"]
        self.away = self.header["away"]
        self.names = {self.home["team_id"]: self.home["name"], self.away["team_id"]: self.away["name"]}
        self.shorts = {self.home["team_id"]: self.home["short"], self.away["team_id"]: self.away["short"]}
        self.allowed_names = {self.home["name"], self.away["name"], self.home["short"], self.away["short"]} | {p["name"] for p in replay.players.values()}
        self.known_event_ids = set(replay._events_by_id.keys())
        self._cue_n = 0

    # ---------------------------------------------------------------- Quant
    def _common_facts(self, elapsed_min: float, snapshot=None) -> tuple[Dict, Dict]:
        """Facts shared by every cue. With an event snapshot, use the state *after* that event."""
        if snapshot is not None:
            pts = dict(snapshot.greeks)
            score_home, score_away = snapshot.score_home, snapshot.score_away
            remaining = max(0, int(round(95.5 - snapshot.clock_min)))
        else:
            g = self.rp.greeks_at(elapsed_min)
            st = self.rp._state_at(elapsed_min)
            pts = g.points()
            score_home, score_away = st.home_goals, st.away_goals
            remaining = int(round(st.remaining_min()))
        lead = score_home - score_away
        leader_id = self.home["team_id"] if lead > 0 else (self.away["team_id"] if lead < 0 else None)
        leader_p = pts["p_home"] if leader_id == self.home["team_id"] else (pts["p_away"] if leader_id == self.away["team_id"] else max(pts["p_home"], pts["p_away"]))
        facts = {
            "home": self.home["name"], "away": self.away["name"], "home_short": self.home["short"], "away_short": self.away["short"],
            "score_home": score_home, "score_away": score_away,
            "p_home_pct": pts["p_home"], "p_draw_pct": pts["p_draw"], "p_away_pct": pts["p_away"],
            "leader": self.names.get(leader_id, "Neither side"), "leader_p_pct": leader_p,
            "remaining_min": remaining,
            "next_goal_swing_home": pts["next_goal_swing_home"], "next_goal_swing_away": pts["next_goal_swing_away"],
            "knife_edge_pts": pts["knife_edge"],
        }
        return facts, pts

    def quant_moments(self) -> List[Moment]:
        moments: List[Moment] = []
        # realised swings: goals and red cards
        biggest_so_far = 0.0
        for s in self.rp.snapshots:
            if s.type == "shot" and s.outcome == "goal":
                f, pts = self._common_facts(s.clock_min, snapshot=s)
                player = self.rp.players.get(s.player_id or "", {})
                team_p = pts["p_home"] if s.team_id == self.home["team_id"] else pts["p_away"]
                biggest_so_far = max(biggest_so_far, abs(s.swing_pts))
                f.update({"player": player.get("name", "Unknown"), "team": self.names[s.team_id], "team_p_pct": team_p, "swing_pts": round(abs(s.swing_pts), 1), "xg": round(s.xg or 0.0, 2), "score_pts": round(abs(s.decomposition["score"]), 1), "momentum_pts": round(abs(s.decomposition["momentum"]), 1), "minute_label": s.label, "biggest_phrase": _BIGGEST[abs(s.swing_pts) >= biggest_so_far]})
                moments.append(Moment("swing", s.clock_min, s.period, s.label, f, [s.event_id], 5, pts))
        # big chances that did not go in: top 3 by expected swing
        chances = [s for s in self.rp.snapshots if s.expected_swing_pts is not None and s.outcome != "goal"]
        chances.sort(key=lambda s: -abs(s.expected_swing_pts or 0))
        for rank, s in enumerate(chances[:3], start=1):
            f, pts = self._common_facts(s.clock_min, snapshot=s)
            player = self.rp.players.get(s.player_id or "", {})
            team_p = pts["p_home"] if s.team_id == self.home["team_id"] else pts["p_away"]
            f.update({"player": player.get("name", "Unknown"), "team": self.names[s.team_id], "xg": round(s.xg or 0.0, 2), "expected_pts": round(abs(s.expected_swing_pts or 0.0), 1), "swing_pts": round(abs(s.swing_pts), 1), "team_p_pct": team_p, "outcome_key": s.outcome, "minute_label": s.label, "chance_rank": rank})
            moments.append(Moment("big_chance", s.clock_min, s.period, s.label, f, [s.event_id], 3, pts))
        # fragility peaks: local maxima of knife-edge above threshold, at most one per 15 minutes
        last_peak = -99
        mins = self.rp.minutes
        for i, m in enumerate(mins):
            k = m.greeks["knife_edge"]
            if k < KNIFE_EDGE_THRESHOLD_PTS or m.elapsed_min - last_peak < 15:
                continue
            prev_k = mins[i - 1].greeks["knife_edge"] if i > 0 else -1
            next_k = mins[i + 1].greeks["knife_edge"] if i + 1 < len(mins) else -1
            if k >= prev_k and k >= next_k and 20 <= m.elapsed_min <= 88:
                last_peak = m.elapsed_min
                f, pts = self._common_facts(float(m.elapsed_min))
                swing_home, swing_away = pts["next_goal_swing_home"], pts["next_goal_swing_away"]
                swing_team_id = self.home["team_id"] if swing_home >= swing_away else self.away["team_id"]
                f.update({"next_goal_swing_max": round(max(swing_home, swing_away), 1), "swing_team": self.names[swing_team_id], "minute_label": m.label})
                ev = self._window_evidence(float(m.elapsed_min))
                moments.append(Moment("knife_edge", float(m.elapsed_min), m.period, m.label, f, ev, 4, pts))
        # theta readings for the leader at ~70' and ~82'
        for target in (70, 82):
            m = next((x for x in mins if x.elapsed_min >= target), None)
            if not m or m.score[0] == m.score[1]:
                continue
            f, pts = self._common_facts(float(m.elapsed_min))
            theta = pts["theta_home"] if m.score[0] > m.score[1] else pts["theta_away"]
            if theta <= 0.15:
                continue
            f.update({"theta_pts_per_min": round(theta, 2), "minute_label": m.label})
            moments.append(Moment("theta", float(m.elapsed_min), m.period, m.label, f, self._window_evidence(float(m.elapsed_min)), 2, pts))
        # vega reading around 60'
        m = next((x for x in mins if x.elapsed_min >= 60), None)
        if m:
            f, pts = self._common_facts(float(m.elapsed_min))
            chaos_id = self.home["team_id"] if pts["vega_home"] > 0 else self.away["team_id"]
            other_id = self.away["team_id"] if chaos_id == self.home["team_id"] else self.home["team_id"]
            vega = abs(pts["vega_home"] if chaos_id == self.home["team_id"] else pts["vega_away"])
            inten = m.intensity_home if chaos_id == self.home["team_id"] else m.intensity_away
            f.update({"chaos_team": self.names[chaos_id], "other_team": self.names[other_id], "vega_pts": round(vega, 1), "chaos_team_tilt_pct": round(100 * inten["recent_tilt"], 0), "minute_label": m.label})
            if vega >= 3.0:
                moments.append(Moment("vega", float(m.elapsed_min), m.period, m.label, f, self._window_evidence(float(m.elapsed_min)), 2, pts))
        # full-time recap
        if self.rp.snapshots:
            last = self.rp.snapshots[-1]
            f, pts = self._common_facts(last.clock_min)
            goals = [s for s in self.rp.snapshots if s.type == "shot" and s.outcome == "goal"]
            summary = self.rp.summary()
            frag = summary["most_fragile_minute"] or {"label": "n/a", "knife_edge": 0.0}
            if goals:
                big = max(goals, key=lambda s: abs(s.swing_pts))
                bp = self.rp.players.get(big.player_id or "", {}).get("name", "Unknown")
                f.update({"biggest_player": bp, "biggest_label": big.label, "biggest_swing_pts": round(abs(big.swing_pts), 1)})
                evidence = [big.event_id]
            else:
                f.update({"biggest_player": "nobody", "biggest_label": "n/a", "biggest_swing_pts": 0.0})
                evidence = [last.event_id]
            ts = summary["team_stats"]
            f.update({"fragile_label": frag["label"], "fragile_pts": round(frag["knife_edge"], 1), "pre_home_pct": round(100 * self.rp.pre_match["p_home"], 1), "xg_home": ts[self.home["team_id"]]["xg"], "xg_away": ts[self.away["team_id"]]["xg"], "minute_label": last.label})
            moments.append(Moment("recap", last.clock_min, last.period, last.label, f, evidence, 5, pts))
        moments.sort(key=lambda m: m.clock_min)
        return moments

    def _window_evidence(self, elapsed_min: float) -> List[int]:
        st = self.rp._state_at(elapsed_min)
        ids = st.recent_shot_ids(self.home["team_id"]) + st.recent_shot_ids(self.away["team_id"])
        if not ids:
            # nearest event at or before this minute
            prev = [s.event_id for s in self.rp.snapshots if s.clock_min <= elapsed_min]
            ids = prev[-1:] if prev else [self.rp.snapshots[0].event_id]
        return sorted(set(ids))

    # ------------------------------------------------------------ Tactician
    def bench_prompts(self, team_id: str, max_per_half: int = 3) -> List[Moment]:
        """Up to three evidenced prompts per half for one bench."""
        prompts: List[Moment] = []
        opp_id = self.rp.state.opp(team_id)
        for m in self.rp.minutes:
            if m.elapsed_min < 15 or m.elapsed_min in (45, 46) or m.elapsed_min > 88:
                continue
            f, pts = self._common_facts(float(m.elapsed_min))
            own_goals = m.score[0] if team_id == self.home["team_id"] else m.score[1]
            opp_goals = m.score[1] if team_id == self.home["team_id"] else m.score[0]
            lead = own_goals - opp_goals
            own_i = m.intensity_home if team_id == self.home["team_id"] else m.intensity_away
            opp_i = m.intensity_away if team_id == self.home["team_id"] else m.intensity_home
            theta_own = pts["theta_home"] if team_id == self.home["team_id"] else pts["theta_away"]
            vega_own = pts["vega_home"] if team_id == self.home["team_id"] else pts["vega_away"]
            swing_against = pts["next_goal_swing_away"] if team_id == self.home["team_id"] else pts["next_goal_swing_home"]
            own_p = pts["p_home"] if team_id == self.home["team_id"] else pts["p_away"]
            team = self.names[team_id]
            opp = self.names[opp_id]
            score_sig = opp_i["recent_xg"] - opp_i["expected_recent_xg"]
            cand = None
            if lead > 0 and swing_against >= 25 and score_sig > 0.15:
                conf = min(0.85, 0.55 + score_sig)
                cand = dict(
                    action_headline=f"Protect the lead: an {opp} goal costs {round(swing_against,1)} points",
                    reason=f"{opp} have created {round(opp_i['recent_xg'],2)} xG in the last 10 minutes against {round(opp_i['expected_recent_xg'],2)} expected. Slow the tempo or add a defender; chaos is worth {round(abs(vega_own),1)} points to them.",
                    action_headline_es=f"Proteger la ventaja: un gol de {opp} cuesta {round(swing_against,1)} puntos",
                    reason_es=f"{opp} ha generado {round(opp_i['recent_xg'],2)} xG en los últimos 10 minutos frente a {round(opp_i['expected_recent_xg'],2)} esperados. Bajar el ritmo o meter un defensa; el caos les vale {round(abs(vega_own),1)} puntos.",
                    action_headline_ta=f"முன்னிலையை காக்கவும்: {opp} கோல் {round(swing_against,1)} புள்ளிகள் இழப்பு",
                    reason_ta=f"கடந்த 10 நிமிடங்களில் {opp} {round(opp_i['recent_xg'],2)} xG உருவாக்கியுள்ளது, எதிர்பார்ப்பு {round(opp_i['expected_recent_xg'],2)}. வேகத்தை குறைக்கவும் அல்லது ஒரு டிஃபென்டரை சேர்க்கவும்; குழப்பம் அவர்களுக்கு {round(abs(vega_own),1)} புள்ளிகள்.",
                    swing_against=round(swing_against, 1), recent_xg_opp=round(opp_i["recent_xg"], 2), expected_xg_opp=round(opp_i["expected_recent_xg"], 2), vega_abs=round(abs(vega_own), 1), window_min=10,
                    action="protect", score_key=2.0 + score_sig,
                )
            elif lead < 0 and m.elapsed_min >= 55 and theta_own < -0.15:
                conf = min(0.8, 0.5 + abs(theta_own))
                cand = dict(
                    action_headline=f"Commit: every minute costs {round(abs(theta_own),2)} points",
                    reason=f"{team} are {own_p}% to win with {f['remaining_min']} minutes left. A more open game adds {round(abs(vega_own),1)} points; push the line higher and press the build-up.",
                    action_headline_es=f"Arriesgar: cada minuto cuesta {round(abs(theta_own),2)} puntos",
                    reason_es=f"{team} tiene un {own_p}% de ganar y quedan {f['remaining_min']} minutos. Un partido más abierto suma {round(abs(vega_own),1)} puntos; subir la línea y presionar la salida.",
                    action_headline_ta=f"தாக்குங்கள்: ஒவ்வொரு நிமிடமும் {round(abs(theta_own),2)} புள்ளிகள் இழப்பு",
                    reason_ta=f"{team} வெற்றி வாய்ப்பு {own_p}%, {f['remaining_min']} நிமிடங்கள் மீதம். திறந்த ஆட்டம் {round(abs(vega_own),1)} புள்ளிகள் சேர்க்கும்; லைனை மேலே தள்ளி அழுத்தம் கொடுக்கவும்.",
                    theta_abs=round(abs(theta_own), 2), own_p_pct=own_p, vega_abs=round(abs(vega_own), 1),
                    action="commit", score_key=1.5 + abs(theta_own),
                )
            elif lead == 0 and m.elapsed_min >= 70 and pts["knife_edge"] >= 25:
                conf = 0.6
                cand = dict(
                    action_headline=f"Level with {f['remaining_min']} left: the next goal is worth {round(pts['knife_edge'],1)} points",
                    reason=f"A draw sits at {f['p_draw_pct']}%. {team} are at {own_p}% to win; recent xG {round(own_i['recent_xg'],2)} against {round(opp_i['recent_xg'],2)} for {opp}. Decide now whether a point is enough.",
                    action_headline_es=f"Empate y quedan {f['remaining_min']}: el próximo gol vale {round(pts['knife_edge'],1)} puntos",
                    reason_es=f"El empate está en {f['p_draw_pct']}%. {team} tiene un {own_p}% de ganar; xG reciente {round(own_i['recent_xg'],2)} frente a {round(opp_i['recent_xg'],2)} de {opp}. Decidir ahora si vale un punto.",
                    action_headline_ta=f"சமநிலை, {f['remaining_min']} நிமிடங்கள்: அடுத்த கோல் {round(pts['knife_edge'],1)} புள்ளிகள்",
                    reason_ta=f"டிரா {f['p_draw_pct']}%. {team} வெற்றி {own_p}%; சமீபத்திய xG {round(own_i['recent_xg'],2)}, {opp} {round(opp_i['recent_xg'],2)}. ஒரு புள்ளி போதுமா என்று இப்போதே முடிவு செய்யுங்கள்.",
                    knife_edge=round(pts["knife_edge"], 1), own_p_pct=own_p, recent_xg_own=round(own_i["recent_xg"], 2), recent_xg_opp=round(opp_i["recent_xg"], 2),
                    action="decide", score_key=1.0,
                )
            if cand:
                score_key = cand.pop("score_key")
                f.update(cand)
                f["confidence_pct"] = int(round(100 * conf))
                f["minute_label"] = m.label
                mom = Moment("bench_prompt", float(m.elapsed_min), m.period, m.label, f, self._window_evidence(float(m.elapsed_min)), 4, pts, confidence=round(conf, 2), action=cand["action"])
                mom.facts["_score_key"] = score_key
                prompts.append(mom)
        # keep the strongest, spaced at least 12 minutes apart, max 3 per half
        chosen: List[Moment] = []
        for half in (1, 2):
            half_prompts = sorted([p for p in prompts if p.period == half], key=lambda p: -p.facts["_score_key"])
            picked: List[Moment] = []
            for p in half_prompts:
                if all(abs(p.clock_min - q.clock_min) >= 12 and p.action != q.action for q in picked):
                    picked.append(p)
                if len(picked) >= max_per_half:
                    break
            chosen += picked
        for p in chosen:
            p.facts.pop("_score_key", None)
        return sorted(chosen, key=lambda p: p.clock_min)

    # ------------------------------------------------------------- Narrator
    def _narrate(self, m: Moment, lang: str, audience: str) -> tuple[str, str, str, VerifierResult]:
        """Returns headline, body, source, verifier result. Rejected drafts are kept in self._draft_log."""
        self._draft_log = []
        facts = dict(m.facts)
        if "outcome_key" in facts:
            facts["outcome_word"] = OUTCOME_WORDS.get(lang, OUTCOME_WORDS["en"]).get(facts["outcome_key"], facts["outcome_key"])
        if "chance_rank" in facts:
            facts["rank_phrase"] = RANK_PHRASES[lang if lang in RANK_PHRASES else "en"][0 if facts["chance_rank"] == 1 else 1]
        if "biggest_phrase" in facts:
            facts["biggest_text"] = BIGGEST_PHRASES[lang if lang in BIGGEST_PHRASES else "en"][facts["biggest_phrase"]]
        public_facts = {k: v for k, v in facts.items() if not k.startswith("_")}
        if self.llm is not None:
            for attempt, source in ((1, "llm"), (2, "llm_retry")):
                try:
                    draft = self._llm_draft(m, public_facts, lang, audience, feedback=None if attempt == 1 else self._last_rejections)
                except Exception as exc:  # network or parsing failure -> fall through to template
                    self._last_rejections = [f"llm error: {exc!r}"]
                    continue
                res = verify_cue(draft["headline"], draft["body"], public_facts, self.allowed_names, m.evidence, self.known_event_ids)
                if res.passed:
                    return draft["headline"], draft["body"], source, res
                self._last_rejections = res.rejections
                self._draft_log.append({"source": source, "headline": draft["headline"], "body": draft["body"], "rejections": res.rejections})
        headline, body = render(m.kind, lang, audience, facts)
        res = verify_cue(headline, body, public_facts, self.allowed_names, m.evidence, self.known_event_ids)
        return headline, body, "template", res

    _last_rejections: List[str] = []
    _draft_log: List[dict] = []

    def _llm_draft(self, m: Moment, facts: Dict, lang: str, audience: str, feedback: Optional[List[str]]) -> Dict:
        system = roles.NARRATOR_SYSTEM if lang == "en" else roles.LOCALISER_SYSTEM
        user = roles.narrator_user_prompt(kind=m.kind, audience=audience, lang=lang, facts=facts, allowed_names=sorted(self.allowed_names), feedback=feedback)
        raw = self.llm.complete(system, user)
        return _parse_json_object(raw)

    # ------------------------------------------------------------------ run
    def run(self, audience: str = "casual", lang: str = "en", max_cues: int = 12, bench_team_id: Optional[str] = None, player_id: Optional[str] = None) -> List[dict]:
        if audience == "bench":
            moments = self.bench_prompts(bench_team_id or self.home["team_id"])
            moments += [m for m in self.quant_moments() if m.kind in ("swing", "recap")]
        else:
            moments = self.quant_moments()
            if audience == "casual":
                moments = [m for m in moments if m.kind in ("swing", "big_chance", "knife_edge", "theta", "recap")]
            if audience == "player_focus" and player_id:
                name = self.rp.players.get(player_id, {}).get("name")
                moments = [m for m in moments if m.facts.get("player") == name or m.kind in ("recap",)]
        moments.sort(key=lambda m: (m.clock_min, -m.priority))
        if len(moments) > max_cues:
            keep = sorted(moments, key=lambda m: (-m.priority, m.clock_min))[:max_cues]
            moments = sorted(keep, key=lambda m: m.clock_min)
        cues: List[dict] = []
        for m in moments:
            headline, body, source, res = self._narrate(m, lang, audience)
            self._cue_n += 1
            t_in = m.clock_min * 60.0
            cues.append({
                "cue_id": f"{self.header['match_id']}-{self._cue_n:03d}",
                "match_id": self.header["match_id"],
                "kind": m.kind,
                "audience": audience,
                "lang": lang,
                "t_in_s": round(t_in, 1),
                "t_out_s": round(t_in + CUE_DURATION_S, 1),
                "priority": m.priority,
                "headline": headline,
                "body": body,
                "facts": {k: v for k, v in m.facts.items() if not k.startswith("_")},
                "evidence_event_ids": m.evidence,
                "greeks": dict(m.greeks),  # probability points (0-100), see Greeks.points()
                "confidence": m.confidence,
                "action": m.action,
                "source": source,
                "verifier": {**res.as_dict(), "rejected_drafts": list(self._draft_log)},
            })
        return cues


def _parse_json_object(raw: str) -> Dict:
    """Extract the first JSON object from a model response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    obj = json.loads(raw[start : end + 1])
    if "headline" not in obj or "body" not in obj:
        raise ValueError("model output missing headline/body")
    return {"headline": str(obj["headline"]).strip(), "body": str(obj["body"]).strip()}


class FaultInjectingLLM:
    """Demo LLM: returns a plausible-looking draft with an invented number and a betting word.

    Used by `/matches/{id}/cues?inject=1` to show the Verifier blocking a bad draft and the
    pipeline falling back to the template. It never produces a grounded draft on purpose.
    """

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        if self.calls % 2 == 1:
            return json.dumps({"headline": "Momentum shift: the odds have swung", "body": "That moment was worth 77 points and the away side now look 88% likely to win."})
        return json.dumps({"headline": "Big moment", "body": "That changed everything: a 63-point swing according to our model."})
