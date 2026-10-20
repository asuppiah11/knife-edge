# Judging guide

Five criteria, 20% each. This page points at the exact files and screens for each.

## 1. Technological implementation

* **Synthetic data creation** — `knifeedge/sim/`. Seeded league (`league.py`), event-level generator with hidden tactical regimes and hidden xG (`match.py`), season generator for ratings (`season.py`). Realism tests: `tests/test_sim.py` (goals, shots, pass completion, pressures, schema validity, determinism, goals vs hidden truth). Schemas: `schemas/`. Provenance statement in every `match.json`.
* **Engine** — closed-form probabilities (`engine/wp.py`), exact finite-difference Greeks (`engine/greeks.py`), explainable live intensity (`engine/state.py`), per-event decomposition (`engine/replay.py`), ratings MLE (`engine/ratings.py`).
* **Calibration** — `knifeedge/calibration.py` → `docs/model-report.md` (Brier, RPS, ECE, reliability diagram) over 500 matches.
* **Hero technologies** — Foundry model client (`agents/foundry_llm.py`), Agent Framework workflow (`agents/foundry_runner.py`), MCP server (`api/mcp_server.py`, tested in `tests/test_api.py`), Copilot Agent Mode configuration (`.github/copilot-instructions.md`, `.vscode/mcp.json`).
* **Quality** — 42 tests (`pytest`), CI (`.github/workflows/ci.yml`), typed dataclasses, docstrings on every module, no secrets (managed identity / `az login`).

## 2. Agentic design & innovation

* Five roles with distinct responsibilities and shared state (the replay + facts + evidence ids): Quant, Tactician, Narrator, Localiser, Verifier — `knifeedge/agents/pipeline.py`, prompts in `agents/roles.py`.
* **Failure recovery** — a draft that fails the deterministic Verifier is retried once with the rejection reasons, then replaced by the template; fault-injection tests in `tests/test_agents.py` (`_BadLLM`, `_AlwaysWrongLLM`).
* **Novelty** — the Greeks framing (Gamma = fragility, Theta = time decay, Vega = chaos sensitivity) is, to our knowledge, new in football match intelligence; `expected swing = xG × delta` ranks chances by how much they *would* have mattered.

## 3. Real-world impact & applicability

* Broadcasters: overlay cue contract (`schemas/overlay_cue.schema.json`) is timed, prioritised and machine-readable; every cue carries the only numbers it may contain and its evidence ids.
* Coaching staff: bench mode limits prompts to three per half with an action, a reason, evidence and a confidence level (`CuePipeline.bench_prompts`).
* Fans: casual mode in English, Spanish and Tamil; plain-language fragility ("knife-edge") instead of probability jargon.
* Production readiness: stateless API, MCP endpoint, SSE streaming, Container Apps deployment notes (`docs/azure.md`), keyless auth, template fallback so the product never goes blank.

## 4. User experience & presentation

* Studio UI: `web/index.html` — scorebug and probability bar, a Greeks band (Delta, Knife-edge, Theta, Vega with sparklines and what-if scenarios), an orbitable 3D pitch with kit-coloured players at each shot and Delta pillars, camera presets, probability river, overlay cue lower-third, event feed and "why it moved" evidence panel. Mode and language switches. No build step; Three.js is vendored in `web/vendor` (MIT) and the fonts in `web/fonts` (OFL).
* Demo video: see the project page.

## 5. Adherence to category

* Grand Prize: explainable match intelligence from synthetic events; narratives, contextual insights, personalised and accessible experiences for fans, analysts and broadcasters.
* Best Use of Microsoft Foundry: Foundry-hosted Narrator/Localiser, tracing and evaluation gate (see `docs/azure.md` for the verification status of each piece).

## Reproduce in two minutes

```bash
pip install -e ".[dev,mcp]"
pytest
knife-edge season --out data/ratings.json
knife-edge generate --seed 42 --out data/matches/KE-000042
knife-edge serve --matches data/matches --ratings data/ratings.json   # open http://localhost:8000 and press Play
```
