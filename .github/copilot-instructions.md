# Copilot instructions for Knife-Edge

Knife-Edge is a live football match-intelligence engine for the Microsoft × Premier League "Inside the Game" hackathon. It measures how much every moment matters (Delta, Gamma, Theta, Vega on the win probability) and explains it through agents.

## House rules

- **Synthetic data only.** Never add, fetch or reference real competition, club, player, match or broadcast data. Fictional clubs come from `knifeedge/sim/league.py`; never add real club or player names anywhere, including tests and docs.
- **No betting language.** No odds, prices, markets, stakes, bookmakers, cash-out, implied odds or fair lines in code, prompts, templates, UI copy or docs. Probabilities are "model estimates of the match state" and are shown as "X% to win".
- **Every number is traceable.** Agent output must come from `facts`; `knifeedge/agents/verifier.py` is the contract. When adding a cue kind, add its facts, its EN/ES/TA templates, and a test in `tests/test_agents.py`.
- **The engine is closed-form.** Probabilities come from `engine/wp.py`; Greeks are finite differences in `engine/greeks.py`. Do not add Monte Carlo to the live path.
- **Keyless auth.** Use `DefaultAzureCredential` / managed identity; never commit keys or connection strings.
- **Tests first.** Run `pytest` before proposing a change; keep the realism ranges in `tests/test_sim.py` passing.

## Where things live

- `knifeedge/sim` generator and hidden truth · `knifeedge/engine` ratings, WP, Greeks, replay · `knifeedge/agents` pipeline, verifier, templates, Foundry/Agent Framework wiring · `knifeedge/api` FastAPI + SSE + MCP · `web/index.html` studio UI · `schemas/` JSON Schemas · `docs/` judging guide, data notes, Azure notes.

## Useful commands

```bash
pip install -e ".[dev,mcp]"
pytest
knife-edge generate --seed 42 --out data/matches/KE-000042
knife-edge serve --matches data/matches --ratings data/ratings.json
```

The Greeks MCP server (`.vscode/mcp.json`) exposes `greeks_now`, `why_it_moved`, `top_moments`, `theta_curve` and `scenario`; use it to inspect a running match instead of reading JSON by hand.
