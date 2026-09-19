"""Provider adapters for NL trade parsing.

Every client exposes ``async complete_json(system, user) -> Completion`` where
``Completion.content`` is the parsed JSON and ``Completion.usage`` carries the
provider's token usage (``None`` for the rule-based baseline). Hosted LLM
models go through a single OpenRouter gateway (OpenAI-compatible
``/chat/completions`` protocol); Ollama shares that protocol locally. The
baseline client wraps the deterministic rule-based parser.
"""

import asyncio
import json
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.nl_parse.models import ModelInfo


@dataclass
class Completion:
    """A provider completion: parsed JSON content plus token usage.

    ``usage`` mirrors the provider's ``usage`` object (e.g. ``prompt_tokens``,
    ``completion_tokens``, ``total_tokens``) and is ``None`` when the provider
    does not report tokens (the rule-based baseline).

    ``model`` is the model the provider says answered, which can differ from the
    one requested when a gateway routes to a dated snapshot. It is recorded so a
    measured result stays attributable to the model that produced it.
    """

    content: dict
    usage: dict | None = None
    model: str | None = None


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

    async def complete_json(self, system: str, user: str) -> Completion:
        from app.services.nl_parse.baseline import parse_rule_based

        return Completion(content=parse_rule_based(user))


class OpenAICompatClient:
    """Works for any OpenAI-compatible endpoint (e.g. local Ollama)."""

    kind = "openai-compatible"

    def __init__(self, base_url: str, api_key: str | None, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def complete_json(self, system: str, user: str) -> Completion:
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
        # Retry a couple of times: Ollama drops the connection while it is
        # loading a cold model into memory; the retry succeeds once loaded.
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=settings.llm_request_timeout_seconds) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return Completion(
                    content=json.loads(content),
                    usage=data.get("usage"),
                    model=data.get("model"),
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 503 and attempt < 2:
                    last_exc = exc
                else:
                    raise RuntimeError(_provider_error(exc)) from exc
            except httpx.TransportError as exc:
                if attempt >= 2:
                    raise RuntimeError(f"cannot reach provider at {self.base_url}: {exc}") from exc
                last_exc = exc
            await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"cannot reach provider at {self.base_url}: {last_exc}") from last_exc


class OpenRouterClient:
    """OpenRouter gateway client (OpenAI-compatible chat completions).

    A single OpenRouter API key provides access to all hosted models.
    """

    kind = "openrouter"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def complete_json(self, system: str, user: str) -> Completion:
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
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return Completion(
            content=json.loads(_strip_code_fences(content)),
            usage=data.get("usage"),
            model=data.get("model"),
        )


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
