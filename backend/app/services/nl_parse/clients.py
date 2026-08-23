"""Provider adapters for NL trade parsing.

Every client exposes ``async complete_json(system, user) -> dict``. OpenAI and
Ollama share an OpenAI-compatible ``/chat/completions`` protocol; Anthropic uses
its Messages API. The baseline client wraps the deterministic rule-based parser.
"""

import json

import httpx

from app.core.config import settings
from app.services.nl_parse.models import ModelInfo


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text


class BaselineClient:
    """Deterministic rule-based parser (no network)."""

    kind = "baseline"

    async def complete_json(self, system: str, user: str) -> dict:
        from app.services.nl_parse.baseline import parse_rule_based

        return parse_rule_based(user)


class OpenAICompatClient:
    """Works for OpenAI and any OpenAI-compatible endpoint (e.g. Ollama)."""

    kind = "openai-compatible"

    def __init__(self, base_url: str, api_key: str | None, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def complete_json(self, system: str, user: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        async with httpx.AsyncClient(timeout=settings.llm_request_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


class AnthropicClient:
    """Anthropic Messages API client."""

    kind = "anthropic"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def complete_json(self, system: str, user: str) -> dict:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        async with httpx.AsyncClient(timeout=settings.llm_request_timeout_seconds) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        text = response.json()["content"][0]["text"]
        return json.loads(_strip_code_fences(text))


def get_client(info: ModelInfo):
    if info.kind == "baseline":
        return BaselineClient()
    if info.kind in ("openai", "ollama"):
        if info.kind == "openai":
            return OpenAICompatClient(settings.openai_base_url, settings.openai_api_key, info.model)
        return OpenAICompatClient(settings.ollama_base_url, None, info.model)
    if info.kind == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("anthropic_api_key is not configured")
        return AnthropicClient(settings.anthropic_api_key, info.model)
    raise ValueError(f"unsupported model kind: {info.kind}")
