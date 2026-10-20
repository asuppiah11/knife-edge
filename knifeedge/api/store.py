"""In-memory match store: loads generated matches, replays them once, caches the replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..engine.ratings import Ratings
from ..engine.replay import MatchReplay, load_match


class MatchStore:
    def __init__(self, matches_dir: Path, ratings_path: Optional[Path] = None):
        self.matches_dir = Path(matches_dir)
        self.ratings = Ratings.from_json(ratings_path) if ratings_path and Path(ratings_path).exists() else None
        self._replays: Dict[str, MatchReplay] = {}
        self._headers: Dict[str, dict] = {}
        self.refresh()

    def refresh(self) -> None:
        if not self.matches_dir.exists():
            return
        for d in sorted(self.matches_dir.iterdir()):
            if (d / "match.json").exists() and (d / "events.jsonl").exists():
                header = json.loads((d / "match.json").read_text())
                self._headers[header["match_id"]] = {**header, "_dir": str(d)}

    def list(self) -> List[dict]:
        out = []
        for mid, h in self._headers.items():
            out.append({"match_id": mid, "home": h["home"], "away": h["away"], "score": h.get("score"), "n_events": None})
        return out

    def header(self, match_id: str) -> dict:
        return self._headers[match_id]

    def replay(self, match_id: str) -> MatchReplay:
        if match_id not in self._replays:
            h = self._headers[match_id]
            header, events = load_match(Path(h["_dir"]))
            priors = self.ratings.expected(header["home"]["team_id"], header["away"]["team_id"]) if self.ratings and header["home"]["team_id"] in self.ratings.attack else None
            self._replays[match_id] = MatchReplay(header, events, priors=priors).run()
        return self._replays[match_id]
