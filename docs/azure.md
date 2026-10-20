# Azure / Foundry setup

Status legend: **done** = runs and is tested here · **wired** = code written, needs a Foundry project to verify · **planned** = not started.

## 0. Prerequisites (laptop)

```bash
az login                          # Azure for Students subscription (KCL email)
az extension add --name ml -y     # optional
pip install -e ".[dev,mcp,azure]" openai
```

## 1. Foundry model deployment — wired

1. Create a Foundry project in **East US 2** or **Sweden Central** (both have the gpt-5.4 family and hosted agents).
2. Deploy `gpt-5.4-mini` (Narrator/Localiser). If the portal reports *insufficient quota*, request an increase immediately and keep template mode for the demo until it lands.
3. Grant yourself **Cognitive Services OpenAI User** on the resource (keyless auth).
4. Test:

```bash
export FOUNDRY_ENDPOINT="https://<resource>.openai.azure.com/"
export FOUNDRY_DEPLOYMENT="gpt-5.4-mini"
python - <<'EOF'
from knifeedge.agents.foundry_llm import FoundryLLM
print(FoundryLLM.from_env().complete("Reply with JSON {\"ok\": true}", "ping"))
EOF
```

`knife-edge serve` picks up `FOUNDRY_ENDPOINT` automatically — the `/health` endpoint reports `"llm": "foundry"`.

## 2. Agent Framework workflow — wired (unverified)

`knifeedge/agents/foundry_runner.py` builds five agents on `AzureOpenAIChatClient` and a Concurrent(Quant, Tactician) → Sequential(Narrator, Localiser, Verifier) workflow, with the Greeks MCP server as a tool. It was written against the 1.0 Python docs without a Foundry project at hand; the first run on the laptop should be `python -m knifeedge.agents.foundry_runner KE-000042` with the API running locally (`KNIFE_EDGE_MCP_URL=http://localhost:8000/mcp/`). Fix any renamed symbols against `pip show agent-framework` docs.

## 3. Tracing and evaluations — planned

* Connect an Application Insights resource to the Foundry project; set `APPLICATIONINSIGHTS_CONNECTION_STRING`; add `azure-monitor-opentelemetry` configure call in `api/app.py` so every cue generation is a span (match_id, cue kind, source, verifier result).
* Evaluation gate: run the Foundry **groundedness** evaluator plus a custom evaluator that calls `verify_cue` over 50 generated cues; fail CI if pass rate < 95%. Script to add: `scripts/eval_gate.py`; workflow step in `.github/workflows/ci.yml`.

## 4. Azure Container Apps — planned

```bash
azd init    # choose "Use code in the current directory" (Python, port 8000)
azd up      # provisions ACA + ACR + Log Analytics, builds the Dockerfile
```

Then in the Container App:
* **Managed identity** on, with *Cognitive Services OpenAI User* on the Foundry resource.
* Env: `FOUNDRY_ENDPOINT`, `FOUNDRY_DEPLOYMENT`, `KNIFE_EDGE_ALLOWED_HOSTS=<your-app>.<region>.azurecontainerapps.io`.
* **Min replicas = 1** from 27 Oct to 10 Nov so judges never hit a cold start.
* Ingress: external, port 8000. The MCP endpoint is `https://<app>/mcp/`.

## 5. GitHub Copilot Agent Mode — configured

`.vscode/mcp.json` registers the Greeks MCP server (and the Azure MCP server) for Copilot Agent Mode; `.github/copilot-instructions.md` tells Copilot the house rules (synthetic data only, no betting language, verifier contract). Make a few visible Copilot-assisted commits.

## Cost

Template mode costs nothing. On gpt-5.4-mini a cue is a few hundred tokens; a full match of cues in three languages is well under a cent. Container Apps at min replicas 1 (0.5 vCPU) is the main cost — a few dollars for the judging window on the student credit.
