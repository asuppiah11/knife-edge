# Infrastructure

Target: one Azure Container App (external ingress, port 8000, min replicas 1) with a system-assigned managed identity that has *Cognitive Services OpenAI User* on the Foundry resource. Application Insights connected to the Foundry project for tracing.

Fastest path (Day 6 of the build plan):

```bash
azd init          # "Use code in the current directory"; it detects the Dockerfile and port 8000
azd env set FOUNDRY_ENDPOINT https://<resource>.openai.azure.com/
azd env set FOUNDRY_DEPLOYMENT gpt-5.4-mini
azd up
```

After the first deploy:

1. Turn on the system-assigned identity for the app and grant it the OpenAI User role on the Foundry resource.
2. Set `KNIFE_EDGE_ALLOWED_HOSTS` to the app FQDN (MCP host check).
3. Set min replicas to 1 for the judging window.
4. Verify `https://<fqdn>/health` reports `"llm": "foundry"` and that `https://<fqdn>/mcp/` answers an MCP `initialize`.

Bicep from `azd init` lands in this folder; commit it once it works.
