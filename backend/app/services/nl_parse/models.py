"""Registry of selectable NL parsing models.

``rule-based`` (the deterministic baseline) is always available. LLM models are
only listed when their API key is configured, so the list works in CI without
any keys. ``ollama`` is listed unconditionally because it is local.
"""

from dataclasses import dataclass
from typing import Literal

from app.core.config import settings


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    kind: Literal["baseline", "openai", "anthropic", "ollama"]
    model: str | None = None


def available_models() -> list[ModelInfo]:
    models: list[ModelInfo] = [
        ModelInfo(id="rule-based", label="Rule-based baseline", kind="baseline")
    ]
    if settings.openai_api_key:
        models.append(
            ModelInfo(
                id="openai-gpt-4o-mini",
                label="OpenAI gpt-4o-mini",
                kind="openai",
                model="gpt-4o-mini",
            )
        )
        models.append(
            ModelInfo(
                id="openai-gpt-4o",
                label="OpenAI gpt-4o",
                kind="openai",
                model="gpt-4o",
            )
        )
    if settings.anthropic_api_key:
        for model in settings.anthropic_models:
            models.append(
                ModelInfo(
                    id=f"anthropic-{model}",
                    label=f"Anthropic {model}",
                    kind="anthropic",
                    model=model,
                )
            )
    models.append(
        ModelInfo(
            id="ollama-llama3",
            label="Local Ollama llama3",
            kind="ollama",
            model="llama3",
        )
    )
    return models


def get_model_info(model_id: str) -> ModelInfo:
    for model in available_models():
        if model.id == model_id:
            return model
    raise ValueError(f"unknown model id: {model_id!r}")
