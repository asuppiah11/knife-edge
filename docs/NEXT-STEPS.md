# Next steps (hand-off to the laptop)

What is done here, offline, and tested:

- Seeded synthetic league + event-level match generator with hidden truth (`knifeedge/sim`)
- Ratings fit, closed-form win probability, Delta/Gamma/Theta/Vega, per-event replay with swing decomposition (`knifeedge/engine`)
- 500-match calibration report with reliability diagram (`docs/model-report.md`)
- Cue pipeline (Quant → Tactician → Narrator → Localiser → Verifier) in template mode, EN/ES/TA, bench prompts, fault-injection tests (`knifeedge/agents`)
- REST API, SSE replay, MCP tool server mounted at `/mcp` (`knifeedge/api`)
- Studio UI (`web/index.html`), Dockerfile, CI workflow, Copilot instructions, MCP config, JSON schemas, judging guide
- 42 passing tests

What needs the laptop / Azure (in order):

1. `git remote add origin <your public repo>` and push. Make sure the repo is public.
2. Foundry: deploy `gpt-5.4-mini`, run the one-line test in `docs/azure.md` §1. If quota blocks you, request it now and keep template mode.
3. With `FOUNDRY_ENDPOINT` set, run `knife-edge serve` and compare `/matches/KE-000042/cues?audience=casual&lang=en` in LLM mode vs template mode. Tune `agents/roles.py` prompts if drafts keep failing the Verifier (the `verifier.rejections` field tells you why).
4. Validate `knifeedge/agents/foundry_runner.py` against the installed `agent-framework` version (it was written from the docs, not executed).
5. Tracing + evaluation gate (`docs/azure.md` §3) — this is the Foundry category story.
6. `azd up` to Container Apps (`infra/README.md`), min replicas 1, managed identity, set `KNIFE_EDGE_ALLOWED_HOSTS`.
7. Review the Tamil and Spanish templates (`docs/localisation.md`).
8. Optional polish: Azure AI Speech "Listen" button; a planted-wrong-number demo toggle in the UI for the video.
9. Record the < 2:00 video (storyboard in the research report), no music, no real crests; fill in the live URL and video link in `README.md`; submit by Tue 27 Oct 18:00 London.
