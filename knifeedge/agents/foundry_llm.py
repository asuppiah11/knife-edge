"""LLM client for Microsoft Foundry (Azure OpenAI-compatible endpoint).

Implements the ``LLM`` protocol used by ``CuePipeline`` with keyless auth
(managed identity on Azure, ``az login`` locally). No API keys in code or
config - see docs/azure.md.

Environment variables
---------------------
FOUNDRY_ENDPOINT     e.g. https://<resource>.openai.azure.com/  (or the Foundry project's OpenAI endpoint)
FOUNDRY_DEPLOYMENT   e.g. gpt-5.4-mini
FOUNDRY_API_VERSION  optional, defaults to a recent preview

Usage
-----
    from knifeedge.agents.foundry_llm import FoundryLLM
    pipe = CuePipeline(replay, llm=FoundryLLM.from_env())
"""

from __future__ import annotations

import os
from typing import Optional


class FoundryLLM:
    def __init__(self, endpoint: str, deployment: str, api_version: Optional[str] = None, temperature: float = 0.4):
        try:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from openai import AzureOpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install openai azure-identity  (or `pip install -e .[azure]`)") from exc
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        self.client = AzureOpenAI(azure_endpoint=endpoint, azure_ad_token_provider=token_provider, api_version=api_version or "2025-04-01-preview")
        self.deployment = deployment
        self.temperature = temperature

    @classmethod
    def from_env(cls) -> "FoundryLLM":
        endpoint = os.environ.get("FOUNDRY_ENDPOINT")
        deployment = os.environ.get("FOUNDRY_DEPLOYMENT", "gpt-5.4-mini")
        if not endpoint:
            raise RuntimeError("FOUNDRY_ENDPOINT is not set")
        return cls(endpoint, deployment, os.environ.get("FOUNDRY_API_VERSION"))

    def complete(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""
