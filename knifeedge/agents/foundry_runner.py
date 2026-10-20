"""Microsoft Agent Framework workflow for Knife-Edge.

STATUS: scaffold. This file was written without access to a Foundry
project and has NOT been executed. Validate it against the installed
``agent-framework`` version on a machine with ``az login`` before relying
on it (API surface follows the 1.0 Python docs; names may have moved).
Everything it orchestrates - the engine, the MCP tools, the templates and
the deterministic Verifier - already runs offline via ``CuePipeline``.

Topology
--------
                 +-----------+
   events  --->  |   Quant   |----+
                 +-----------+    |      +-----------+     +------------+     +-----------+
                                  +--->  | Narrator  | --> | Localiser  | --> | Verifier  | --> cue
                 +-----------+    |      +-----------+     +------------+     +-----------+
   events  --->  | Tactician |----+         (LLM)             (LLM)          (deterministic +
                 +-----------+                                                LLM groundedness)

Quant and Tactician run concurrently and both read the engine through the
Greeks MCP server (knifeedge.api.mcp_server). Narrator and Localiser are
Foundry-hosted chat agents. The Verifier wraps ``verify_cue`` and, on a
rejection, hands the draft back to the Narrator once before falling back
to the template.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

from . import roles

MCP_URL = os.environ.get("KNIFE_EDGE_MCP_URL", "http://localhost:8000/mcp")


def build_agents() -> Dict[str, Any]:
    """Create the five agents on a Foundry model. Requires `pip install agent-framework azure-identity`."""
    from agent_framework import MCPStreamableHTTPTool  # type: ignore
    from agent_framework.azure import AzureOpenAIChatClient  # type: ignore
    from azure.identity import DefaultAzureCredential

    client = AzureOpenAIChatClient(
        credential=DefaultAzureCredential(),
        endpoint=os.environ["FOUNDRY_ENDPOINT"],
        deployment_name=os.environ.get("FOUNDRY_DEPLOYMENT", "gpt-5.4-mini"),
    )
    greeks_tools = MCPStreamableHTTPTool(name="knife_edge_greeks", url=MCP_URL)
    return {
        "quant": client.create_agent(name="Quant", instructions=roles.QUANT_SYSTEM, tools=greeks_tools),
        "tactician": client.create_agent(name="Tactician", instructions=roles.TACTICIAN_SYSTEM, tools=greeks_tools),
        "narrator": client.create_agent(name="Narrator", instructions=roles.NARRATOR_SYSTEM),
        "localiser": client.create_agent(name="Localiser", instructions=roles.LOCALISER_SYSTEM),
        "verifier": client.create_agent(name="Verifier", instructions=roles.VERIFIER_SYSTEM),
    }


def build_workflow(agents: Dict[str, Any]):
    """Quant || Tactician  ->  Narrator  ->  Localiser  ->  Verifier."""
    from agent_framework import ConcurrentBuilder, SequentialBuilder  # type: ignore

    analysis = ConcurrentBuilder().participants([agents["quant"], agents["tactician"]]).build()
    return SequentialBuilder().participants([analysis, agents["narrator"], agents["localiser"], agents["verifier"]]).build()


async def run_once(match_id: str, elapsed_min: float, lang: str = "en", audience: str = "casual") -> List[Dict]:
    agents = build_agents()
    workflow = build_workflow(agents)
    prompt = f"Match {match_id} at minute {elapsed_min:.0f}. Audience={audience}, language={lang}. Produce the overlay cues for this moment."
    outputs: List[Dict] = []
    async for event in workflow.run_stream(prompt):  # type: ignore[attr-defined]
        outputs.append({"type": type(event).__name__, "data": getattr(event, "data", None)})
    return outputs


if __name__ == "__main__":  # pragma: no cover
    import sys

    mid = sys.argv[1] if len(sys.argv) > 1 else "KE-000042"
    print(asyncio.run(run_once(mid, 60)))
