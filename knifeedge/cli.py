"""Command-line entry point: `knife-edge <command>` (or `python -m knifeedge.cli`).

    knife-edge generate --seed 42 --out data/matches/KE-000042
    knife-edge season   --out data/ratings.json
    knife-edge replay   data/matches/KE-000042 --ratings data/ratings.json
    knife-edge calibrate --matches 500 --out docs
    knife-edge cues     data/matches/KE-000042 --ratings data/ratings.json --lang en --audience casual
    knife-edge serve    --matches data/matches --ratings data/ratings.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_generate(args: argparse.Namespace) -> int:
    from .sim import SimConfig, build_league, simulate_match

    league = build_league(args.league_seed)
    cfg = SimConfig(texture=not args.fast)
    sim = simulate_match(seed=args.seed, league=league, home_idx=args.home, away_idx=args.away, config=cfg, matchday=args.matchday)
    out = Path(args.out or f"data/matches/{sim.match_id}")
    sim.write(out)
    h = sim.match_header()
    print(f"{h['home']['name']} {h['score']['home']}-{h['score']['away']} {h['away']['name']}  ({len(sim.events)} events) -> {out}")
    return 0


def cmd_season(args: argparse.Namespace) -> int:
    from .engine.ratings import fit_ratings
    from .sim import build_league
    from .sim.season import generate_season, season_table

    league = build_league(args.league_seed)
    results = generate_season(league, seed=args.league_seed + 4)
    ratings = fit_ratings(results, [t.team_id for t in league.teams])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ratings.to_json(out)
    names = {t.team_id: t.name for t in league.teams}
    print(f"Fitted ratings on {len(results)} results -> {out}")
    for row in season_table(results)[:5]:
        print(f"  {names[row['team_id']]:<22} {row['Pts']} pts  GD {row['GF'] - row['GA']:+d}")
    return 0


def _priors_for(header: dict, ratings_path: str | None):
    if not ratings_path:
        return None
    from .engine.ratings import Ratings

    r = Ratings.from_json(Path(ratings_path))
    return r.expected(header["home"]["team_id"], header["away"]["team_id"])


def cmd_replay(args: argparse.Namespace) -> int:
    from .engine.replay import load_match, MatchReplay

    header, events = load_match(Path(args.match_dir))
    rp = MatchReplay(header, events, priors=_priors_for(header, args.ratings)).run()
    rp.write(Path(args.match_dir))
    s = rp.summary()
    print(f"{header['home']['name']} {header['score']['home']}-{header['score']['away']} {header['away']['name']}")
    print(f"pre-match P(home/draw/away) = {s['pre_match']}")
    print("Biggest moments:")
    for m in s["biggest_moments"]:
        who = (m.get("player") or {}).get("name", "?")
        print(f"  {m['label']:>6} {m['type']:<6} {str(m['outcome'] or ''):<10} {who:<22} swing {m['swing_pts']:+.1f} pts  {m['decomposition']}")
    print(f"Most fragile minute: {s['most_fragile_minute']}")
    print("Team stats:", json.dumps(s["team_stats"], indent=1))
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    from .calibration import run_calibration

    r = run_calibration(n_matches=args.matches, out_dir=Path(args.out), plot=not args.no_plot, league_seed=args.league_seed)
    for name, m in r["models"].items():
        print(f"{name:<10} brier {m['brier']:.4f}  rps {m['rps']:.4f}  ece {m['ece_home']:.4f}")
    print(f"-> {args.out}/model-report.md")
    return 0


def cmd_cues(args: argparse.Namespace) -> int:
    from .agents.pipeline import CuePipeline
    from .engine.replay import load_match, MatchReplay

    header, events = load_match(Path(args.match_dir))
    rp = MatchReplay(header, events, priors=_priors_for(header, args.ratings)).run()
    pipe = CuePipeline(rp, llm=None)  # template mode; pass a Foundry client for LLM mode
    cues = pipe.run(audience=args.audience, lang=args.lang, max_cues=args.max)
    for c in cues:
        print(f"[{c['kind']:<11}] {c['t_in_s']:>6.0f}s  {c['headline']}  --  {c['body']}  (verifier: {'pass' if c['verifier']['passed'] else 'FAIL'}; source={c['source']})")
    if args.out:
        Path(args.out).write_text(json.dumps(cues, indent=2, ensure_ascii=False))
        print(f"-> {args.out}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api.app import create_app

    app = create_app(matches_dir=Path(args.matches), ratings_path=Path(args.ratings) if args.ratings else None)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="knife-edge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate one synthetic match (events.jsonl, match.json, truth.json)")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--league-seed", type=int, default=7)
    g.add_argument("--home", type=int, default=None, help="home team index 0-19 (random if omitted)")
    g.add_argument("--away", type=int, default=None)
    g.add_argument("--matchday", type=int, default=1)
    g.add_argument("--fast", action="store_true", help="shots/goals/cards only, no passing texture")
    g.add_argument("--out", default=None)
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("season", help="generate a season of results and fit pre-match ratings")
    s.add_argument("--league-seed", type=int, default=7)
    s.add_argument("--out", default="data/ratings.json")
    s.set_defaults(func=cmd_season)

    r = sub.add_parser("replay", help="replay a match through the engine and write timeline/minutes/summary")
    r.add_argument("match_dir")
    r.add_argument("--ratings", default=None)
    r.set_defaults(func=cmd_replay)

    c = sub.add_parser("calibrate", help="evaluate calibration over N simulated matches")
    c.add_argument("--matches", type=int, default=500)
    c.add_argument("--league-seed", type=int, default=7)
    c.add_argument("--out", default="docs")
    c.add_argument("--no-plot", action="store_true")
    c.set_defaults(func=cmd_calibrate)

    q = sub.add_parser("cues", help="produce overlay cues for a match (template mode, no LLM needed)")
    q.add_argument("match_dir")
    q.add_argument("--ratings", default=None)
    q.add_argument("--audience", default="casual", choices=["casual", "analyst", "bench", "player_focus"])
    q.add_argument("--lang", default="en", choices=["en", "es", "ta"])
    q.add_argument("--max", type=int, default=12)
    q.add_argument("--out", default=None)
    q.set_defaults(func=cmd_cues)

    v = sub.add_parser("serve", help="run the HTTP API")
    v.add_argument("--matches", default="data/matches")
    v.add_argument("--ratings", default=None)
    v.add_argument("--host", default="0.0.0.0")
    v.add_argument("--port", type=int, default=8000)
    v.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
