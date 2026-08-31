"""Provider adapters for NL trade parsing.

Every client exposes ``async complete_json(system, user) -> dict``. Hosted LLM
models go through a single OpenRouter gateway (OpenAI-compatible
``/chat/completions`` protocol); Ollama shares that protocol locally. The
baseline client wraps the deterministic rule-based parser.
"""

import json

import httpx

from app.core.config import settings
from app.services.nl_parse.models import ModelInfo


def _provider_error(exc: httpx.HTTPStatusError) -> str:
    """Build a human-readable message from a provider error response."""
    try:
        body = exc.response.json()
        message = (
            body.get("error", {}).get("message", "")
            or body.get("message", "")
            or exc.response.text
        )
    except Exception:
        message = exc.response.text
    return f"LLM provider error ({exc.response.status_code}): {message}"


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
    """Works for any OpenAI-compatible endpoint (e.g. local Ollama)."""

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
        try:
            async with httpx.AsyncClient(timeout=settings.llm_request_timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_provider_error(exc)) from exc
        except httpx.TransportError as exc:
            raise RuntimeError(f"cannot reach provider at {self.base_url}: {exc}") from exc
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


class OpenRouterClient:
    """OpenRouter gateway client (OpenAI-compatible chat completions).

    A single OpenRouter API key provides access to all hosted models.
    """

    kind = "openrouter"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def complete_json(self, system: str, user: str) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/monamengyu/project_fx_trading_system",
            "X-Title": "FX Trading System",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.llm_request_timeout_seconds) as client:
                response = await client.post(
                    f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_provider_error(exc)) from exc
        except httpx.TransportError as exc:
            raise RuntimeError(
                f"cannot reach OpenRouter at {settings.openrouter_base_url}: {exc}"
            ) from exc
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(_strip_code_fences(content))


def get_client(info: ModelInfo):
    if info.kind == "baseline":
        return BaselineClient()
    if info.kind == "openrouter":
        if not settings.openrouter_api_key:
            raise RuntimeError("openrouter_api_key is not configured")
        return OpenRouterClient(settings.openrouter_api_key, info.model)
    if info.kind == "ollama":
        return OpenAICompatClient(settings.ollama_base_url, None, info.model)
    raise ValueError(f"unsupported model kind: {info.kind}")
