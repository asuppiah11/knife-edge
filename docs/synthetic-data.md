# Synthetic data: how it is made and why it is honest

Everything in `data/` is produced by `knifeedge.sim`. No real competition, club, player, match, tracking or broadcast data was used at any point. Club and player names are invented; any resemblance is coincidental.

## Files per match

| File | Who reads it | Contents |
|---|---|---|
| `match.json` | engine, agents, UI | header: clubs, squads, score, periods, provenance statement |
| `events.jsonl` | engine, agents, UI | ~2,000 events: passes, carries, shots (with observable xG), pressures, tackles, interceptions, fouls, cards, substitutions, dead balls |
| `truth.json` | calibration only | hidden tactical regimes per team over time, true per-minute goal intensities, hidden xG per shot, player physical totals |

Coordinates are in the acting team's attacking frame (x → 105 is the opponent's goal). Schemas live in `schemas/`.

## Generation

1. **League** (`league.py`): 20 clubs with Dixon-Coles-style attack and defence strengths (log-scale, centred), a home advantage, a preferred style (high press, possession, low block/counter, balanced) and 18-player squads with hidden attributes (pace, passing, finishing, pressing, top speed).
2. **Regimes** (`match.py`): every five minutes each team may switch tactical regime; the transition depends on its style, the score and the clock (leading late → game management; trailing → press/open; a red card → low block). Regimes change goal intensities, pressures per minute, pass completion, tempo and possession share. They are recorded in `truth.json` and never shown to the engine.
3. **Goals**: per minute, each team's true intensity is `base/90 × score-state × men × late-game × own regime × opponent regime`. Shots per minute are Poisson(intensity / mean hidden xG for that regime pair), each shot gets a location, body part, pressure flag and situation (open play, counter, set piece, penalty), an *observable* xG from the public formula in `engine/features.py` and a *hidden* xG that adds shooter finishing and noise. Goals are Bernoulli(hidden xG), so expected goals per minute equal the true intensity.
4. **Texture**: possession sequences fill the remaining seconds — passes with length/forwardness-based difficulty, carries with speeds drawn from the player's top speed (sprint tag ≥ 7 m/s), pressures by the opponent (more under a high press), tackles, interceptions, throw-ins, goal kicks, corners, fouls and cards, substitutions after 55'.
5. **Fast mode** (`SimConfig(texture=False)`) keeps only the goal process, cards and substitutions; it is used for the 500-match calibration run.

## Realism targets (checked by `tests/test_sim.py`)

| Quantity | Target | Generator |
|---|---|---|
| Goals per match | 2.6–3.0 | ≈ 2.8 |
| Shots per match | 22–28 | ≈ 24 |
| Mean xG per shot | 0.10–0.15 | ≈ 0.12–0.14 |
| Pass completion | 80–85% | ≈ 83% |
| Events per match | 1,700–2,300 | ≈ 2,100 |
| Pressures per team | 100–250 | ≈ 150 |

## Why hidden truth matters

Because the generator records what the engine cannot see, we can score the engine the way a real deployment would be scored — against outcomes — and publish the result (`docs/model-report.md`). The engine's state multipliers are deliberately *not* the simulator's, so it faces the same kind of mis-specification a model of real football would.
