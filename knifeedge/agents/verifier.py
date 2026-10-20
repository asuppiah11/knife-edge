"""Deterministic Verifier: no number, name or claim reaches the screen unless it is in the facts.

Checks (all must pass):
1. Every number in the text matches a value in ``facts`` (tolerance-aware).
2. Every proper name in the text is an allowed player or team name.
3. No banned vocabulary (odds, betting, prices, markets).
4. Every evidence event id exists in the match.
5. Length limits of the overlay contract.

This is intentionally boring. The LLM can be creative; the Verifier cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

BANNED = [
    "odds", "bet", "bets", "betting", "bookmaker", "bookie", "bookies", "stake", "staking", "wager", "wagering",
    "price", "priced", "pricing", "market", "markets", "cash out", "parlay", "accumulator", "punter", "implied odds",
    "fair line", "moneyline", "spread bet", "gamble", "gambling", "kelly",
    # Spanish
    "apuesta", "apuestas", "apostar", "cuota", "cuotas", "casa de apuestas", "apostador",
    # Tamil
    "பந்தயம்", "சூதாட்டம்", "பெட்டிங்",
]
_ASCII_BANNED = [b for b in BANNED if b.isascii()]
_OTHER_BANNED = [b for b in BANNED if not b.isascii()]
# \b is unreliable for Tamil combining marks, so non-ASCII terms match without word boundaries
_BANNED_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in _ASCII_BANNED) + r")\b" + (r"|(" + "|".join(re.escape(b) for b in _OTHER_BANNED) + r")" if _OTHER_BANNED else ""),
    re.IGNORECASE,
)
_NUM_RE = re.compile(r"(?<![A-Za-z\d])[-+]?\d+(?:[.,]\d+)?")
_SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)")
_LABEL_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\+\d{1,2})?)'")
_NAME_STOP = {
    "The", "A", "An", "In", "At", "On", "For", "With", "And", "But", "Home", "Away", "Half", "Goal", "Shot", "Red", "Yellow",
    "Card", "Knife", "Edge", "Match", "Minute", "Minutes", "Swing", "Theta", "Delta", "Gamma", "Vega", "Chaos", "Time",
    "Next", "First", "Second", "Big", "Chance", "Save", "Saved", "Post", "Now", "Still", "Lead", "Level", "Full", "Kick",
    "Off", "Protect", "Commit", "Hold", "Press", "Push", "Slow", "Drop", "Consider", "Recent", "Expected", "Field", "Tilt",
    "No", "Not", "Yes", "If", "It", "They", "Their", "Them", "Your", "You", "We", "Our", "Up", "Down", "Gaining", "Losing",
    "League", "Synthetic", "Momentum", "Evidence", "Confidence", "Action", "Window", "Points", "Point", "Pts",
    "Blocked", "Wide", "Over", "Under", "High", "Low", "Pressure", "Counter", "Open", "Play", "Set", "Piece", "Penalty",
    # Spanish
    "Un", "Una", "El", "La", "Los", "Las", "Gol", "Final", "Giro", "Al", "Filo", "Proteger", "Arriesgar", "Empate", "Esa",
    "Nada", "Si", "Cada", "Fragilidad", "Theta", "Vega", "Marcador", "Decidir", "Confianza", "Quedan", "Bajar", "Subir",
}
HEADLINE_MAX = 80
BODY_MAX = 320


@dataclass
class VerifierResult:
    passed: bool
    checks: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"passed": self.passed, "checks": self.checks, "rejections": self.rejections}


def _flatten_numbers(facts: Dict) -> List[float]:
    out: List[float] = []
    for v in facts.values():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
        elif isinstance(v, (list, tuple)):
            out.extend(float(x) for x in v if isinstance(x, (int, float)) and not isinstance(x, bool))
        elif isinstance(v, dict):
            out.extend(_flatten_numbers(v))
    return out


def _number_allowed(n: float, allowed: Iterable[float]) -> bool:
    for a in allowed:
        tol = 0.051 if abs(a) < 1.0 else 0.51
        if abs(n - a) <= tol:
            return True
        # allow a probability quoted as a percentage or vice versa
        if abs(a) <= 1.0 and abs(n - 100 * a) <= 0.51:
            return True
    return False


_WORD_RE = re.compile(r"^[A-Z][a-z][a-zA-Z\-]*$")  # Capitalised word, not an all-caps code like SAL


def _proper_name_candidates(text: str) -> Set[str]:
    """Capitalised bigrams inside one sentence, e.g. 'Arlo Brandt', 'Carrow Vale'."""
    cands: Set[str] = set()
    text = re.sub(r"'s\b", "", text)  # possessives
    for sentence in re.split(r"[.!?:;|()\[\]]", text):
        words = [w.strip(",\"'") for w in sentence.split()]
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if _WORD_RE.match(w1) and _WORD_RE.match(w2) and w1 not in _NAME_STOP and w2 not in _NAME_STOP:
                cands.add(f"{w1} {w2}")
    return cands


def _strip_scorelines_and_labels(text: str, facts: Dict) -> tuple[str, List[str]]:
    """Remove scorelines (1-1) and minute labels (45+2') after checking them against facts."""
    rejections: List[str] = []
    allowed_numbers = _flatten_numbers(facts)
    string_facts = {str(v) for v in facts.values() if isinstance(v, str)}

    def _score(m):
        a, b = float(m.group(1)), float(m.group(2))
        if not (_number_allowed(a, allowed_numbers) and _number_allowed(b, allowed_numbers)):
            rejections.append(f"scoreline not in facts: {m.group(0)}")
        return " "

    def _label(m):
        if m.group(0) not in string_facts and m.group(1) + "'" not in string_facts:
            rejections.append(f"minute label not in facts: {m.group(0)}")
        return " "

    text = _LABEL_RE.sub(_label, text)
    text = _SCORE_RE.sub(_score, text)
    return text, rejections


def verify_cue(headline: str, body: str, facts: Dict, allowed_names: Iterable[str], evidence_event_ids: Iterable[int], known_event_ids: Optional[Set[int]] = None) -> VerifierResult:
    text = f"{headline} | {body}"
    checks: List[str] = []
    rejections: List[str] = []

    # 1. numbers (scorelines and minute labels are checked as units first)
    allowed_numbers = _flatten_numbers(facts)
    stripped, rej = _strip_scorelines_and_labels(text, facts)
    rejections.extend(rej)
    found = [float(m.group(0).replace(",", ".")) for m in _NUM_RE.finditer(stripped)]
    bad = [n for n in found if not _number_allowed(n, allowed_numbers)]
    if bad:
        rejections.append(f"numbers not in facts: {sorted(set(bad))}")
    checks.append(f"numbers:{len(found)} checked")

    # 2. names
    allowed = set(allowed_names)
    allowed_lower = {a.lower() for a in allowed}
    cands = _proper_name_candidates(text)
    unknown = [c for c in cands if c.lower() not in allowed_lower and not any(c.lower() in a.lower() for a in allowed)]
    if unknown:
        rejections.append(f"unknown names: {sorted(unknown)}")
    checks.append(f"names:{len(cands)} checked")

    # 3. banned vocabulary
    m = _BANNED_RE.search(text)
    if m:
        rejections.append(f"banned vocabulary: '{m.group(0)}'")
    checks.append("vocabulary")

    # 4. evidence
    ev = list(evidence_event_ids)
    if not ev:
        rejections.append("no evidence event ids")
    elif known_event_ids is not None:
        missing = [e for e in ev if e not in known_event_ids]
        if missing:
            rejections.append(f"evidence ids not in match: {missing}")
    checks.append(f"evidence:{len(ev)} ids")

    # 5. lengths
    if len(headline) > HEADLINE_MAX:
        rejections.append(f"headline too long ({len(headline)} > {HEADLINE_MAX})")
    if len(body) > BODY_MAX:
        rejections.append(f"body too long ({len(body)} > {BODY_MAX})")
    if not headline.strip() or not body.strip():
        rejections.append("empty headline or body")
    checks.append("length")

    return VerifierResult(passed=not rejections, checks=checks, rejections=rejections)
