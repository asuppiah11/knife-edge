"""Seeded synthetic league: 20 fictional clubs, squads, Dixon-Coles-style strengths.

Club and player names are invented. Any resemblance to a real club, player
or competition is coincidental and unintended; the generator never reads
real data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

CLUB_NAMES: List[tuple[str, str, str]] = [
    # (name, short, kit colour)
    ("Aldbury Wanderers", "ALD", "#1f6fb2"),
    ("Blackmere Town", "BLK", "#222222"),
    ("Carrow Vale", "CAR", "#2e8b57"),
    ("Dunston Rovers", "DUN", "#b22222"),
    ("Eastmoor United", "EAS", "#ff8c00"),
    ("Fernhollow Athletic", "FER", "#006400"),
    ("Greyfield City", "GRE", "#708090"),
    ("Hollin Park", "HOL", "#800080"),
    ("Ingleby Forest", "ING", "#228b22"),
    ("Kestrel Bay", "KES", "#1e90ff"),
    ("Langford City", "LAN", "#dc143c"),
    ("Mossridge", "MOS", "#556b2f"),
    ("Northam Albion", "NOR", "#ffffff"),
    ("Oakenshaw", "OAK", "#8b4513"),
    ("Pennard Rangers", "PEN", "#4169e1"),
    ("Redwater", "RED", "#c41e3a"),
    ("Saltmarsh", "SAL", "#20b2aa"),
    ("Thornsett", "THO", "#daa520"),
    ("Umberly", "UMB", "#4b0082"),
    ("Wrenfield", "WRE", "#ffd700"),
]

# Invented name pools. Deliberately broad so squads do not look like any one nation.
FIRST_NAMES = [
    "Arlo", "Benedek", "Cassius", "Dario", "Elian", "Fynn", "Gavriel", "Hamza", "Idris", "Jonas",
    "Kaspar", "Leandro", "Mateus", "Nikolai", "Oisin", "Pavel", "Quinlan", "Rafael", "Soren", "Tariq",
    "Uriel", "Viggo", "Wesley", "Xavi", "Yusuf", "Zane", "Amadou", "Bastian", "Caleb", "Dmitri",
    "Emeka", "Felix", "Gideon", "Hugo", "Ismael", "Jaden", "Kian", "Luca", "Milo", "Nestor",
    "Otis", "Pedro", "Rhys", "Samir", "Teodor", "Ulrik", "Vasco", "Wilfred", "Yann", "Zoran",
    "Arjun", "Karthik", "Vikram", "Aarav", "Rohan", "Senthil", "Thiago", "Marco", "Joaquin", "Enzo",
]
LAST_NAMES = [
    "Ashcombe", "Brandt", "Calloway", "Dalgety", "Esterhuizen", "Farrant", "Gallo", "Haverford", "Ivashko", "Jarrow",
    "Kessler", "Lindqvist", "Moreau", "Nakamura", "Okonkwo", "Pellegrino", "Quarrie", "Rasmussen", "Sandoval", "Thorne",
    "Ulloa", "Varga", "Whitlock", "Yilmaz", "Zabala", "Abara", "Beaumont", "Castellano", "Draper", "Eriksen",
    "Fontaine", "Grimaldi", "Hartwell", "Iqbal", "Jensen", "Kovac", "Larsson", "Mendes", "Novak", "Oyelaran",
    "Pretorius", "Rowntree", "Soler", "Tanaka", "Umeh", "Vickery", "Walsh", "Yared", "Zielinski", "Ahmed",
    "Subramaniam", "Rajan", "Menon", "Pillai", "Fernandes", "Delgado", "Alvarez", "Ribeiro", "Costa", "Silva",
]

POSITIONS_433 = ["GK", "RB", "CB", "CB", "LB", "CM", "CM", "CM", "RW", "ST", "LW"]
BENCH_POSITIONS = ["GK", "CB", "FB", "CM", "CM", "W", "ST"]


@dataclass
class Player:
    player_id: str
    name: str
    position: str
    shirt: int
    starter: bool
    # attributes in [0,1]; hidden from the engine, visible only through behaviour
    pace: float
    passing: float
    finishing: float
    pressing: float
    top_speed_ms: float

    def public(self) -> dict:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "position": self.position,
            "shirt": self.shirt,
            "starter": self.starter,
        }


@dataclass
class Team:
    team_id: str
    name: str
    short: str
    colour: str
    attack: float  # log-scale attack strength (Dixon-Coles alpha)
    defence: float  # log-scale defence strength (Dixon-Coles beta); higher = leakier
    style: str  # preferred regime
    players: List[Player] = field(default_factory=list)
    formation: str = "4-3-3"

    def starters(self) -> List[Player]:
        return [p for p in self.players if p.starter]

    def public(self) -> dict:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "short": self.short,
            "colour": self.colour,
            "formation": self.formation,
        }


@dataclass
class League:
    seed: int
    teams: List[Team]
    home_advantage: float  # log-scale, e.g. 0.25 -> ~28% more goals at home
    base_goal_rate: float  # league-average goals per team per 90 (exp(intercept))

    def by_id(self) -> Dict[str, Team]:
        return {t.team_id: t for t in self.teams}

    def expected_goals(self, home: Team, away: Team) -> tuple[float, float]:
        """Pre-match expected goals per 90 for (home, away) from strengths."""
        lam_h = self.base_goal_rate * np.exp(home.attack + away.defence + self.home_advantage)
        lam_a = self.base_goal_rate * np.exp(away.attack + home.defence)
        return float(lam_h), float(lam_a)


STYLES = ["high_press", "possession", "low_block_counter", "balanced"]


def _make_squad(rng: np.random.Generator, team_idx: int, quality: float) -> List[Player]:
    players: List[Player] = []
    used = set()
    shirt = 1
    slots = [(pos, True) for pos in POSITIONS_433] + [(pos, False) for pos in BENCH_POSITIONS]
    for pos, starter in slots:
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in used:
                used.add(name)
                break
        pace = float(np.clip(rng.normal(0.55 + 0.15 * quality, 0.12), 0.2, 0.95))
        if pos in ("RW", "LW", "W", "RB", "LB", "FB"):
            pace = min(0.98, pace + 0.12)
        passing = float(np.clip(rng.normal(0.55 + 0.2 * quality, 0.12), 0.2, 0.95))
        if pos in ("CM",):
            passing = min(0.98, passing + 0.1)
        finishing = float(np.clip(rng.normal(0.45 + 0.2 * quality, 0.15), 0.1, 0.95))
        if pos in ("ST", "RW", "LW", "W"):
            finishing = min(0.98, finishing + 0.15)
        pressing = float(np.clip(rng.normal(0.5 + 0.15 * quality, 0.15), 0.1, 0.95))
        top_speed = 7.6 + 2.4 * pace  # 7.6..10.0 m/s (27..36 km/h)
        players.append(
            Player(
                player_id=f"T{team_idx:02d}P{shirt:02d}",
                name=name,
                position=pos,
                shirt=shirt,
                starter=starter,
                pace=pace,
                passing=passing,
                finishing=finishing,
                pressing=pressing,
                top_speed_ms=float(top_speed),
            )
        )
        shirt += 1
    return players


def build_league(seed: int = 7, n_teams: int = 20) -> League:
    """Build a deterministic league. The same seed always yields the same clubs,
    squads and strengths."""
    rng = np.random.default_rng(seed)
    n = min(n_teams, len(CLUB_NAMES))
    # Attack/defence strengths: spread chosen so the best side scores ~2.2/90 and
    # the worst ~0.9/90 against an average opponent. Centred at 0 (sum-to-zero).
    attack = rng.normal(0.0, 0.28, n)
    defence = rng.normal(0.0, 0.22, n)
    attack -= attack.mean()
    defence -= defence.mean()
    teams: List[Team] = []
    for i in range(n):
        name, short, colour = CLUB_NAMES[i]
        quality = float(np.clip((attack[i] - defence[i]) / 0.6, -1, 1))
        style = str(rng.choice(STYLES, p=[0.3, 0.3, 0.25, 0.15]))
        team = Team(
            team_id=f"T{i:02d}",
            name=name,
            short=short,
            colour=colour,
            attack=float(attack[i]),
            defence=float(defence[i]),
            style=style,
            players=_make_squad(rng, i, quality),
        )
        teams.append(team)
    # Pre-match baseline 1.10 * e^0.22 + 1.10 = 2.47 goals per 90; score-state, late-game and
    # stoppage effects in the simulator lift realised totals to ~2.8-2.9 per match (league-typical).
    return League(seed=seed, teams=teams, home_advantage=0.22, base_goal_rate=1.10)
