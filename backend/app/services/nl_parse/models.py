"""Registry of selectable NL parsing models.

``rule-based`` (the deterministic baseline) is always available. Hosted LLM
models are exposed through a single OpenRouter gateway and are only listed when
``OPENROUTER_API_KEY`` is configured, so the list works in CI without any keys.
``ollama`` is listed unconditionally because it is local and keyless.
"""

from dataclasses import dataclass
from typing import Literal

from app.core.config import settings


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    kind: Literal["baseline", "openrouter", "ollama"]
    model: str | None = None


def _label_for(model_id: str) -> str:
    provider, _, name = model_id.partition("/")
    return f"{provider} {name}" if provider else model_id


def available_models() -> list[ModelInfo]:
    models: list[ModelInfo] = [
        ModelInfo(
            id="rule-based",
            label="Rule-based baseline",
            kind="baseline",
        )
    ]
    if settings.openrouter_api_key:
        for model_id in settings.openrouter_models:
            models.append(
                ModelInfo(
                    id=model_id,
                    label=_label_for(model_id),
                    kind="openrouter",
                    model=model_id,
                )
            )
    for model_id in settings.ollama_models:
        models.append(
            ModelInfo(
                id=model_id,
                label=f"Local Ollama {model_id}",
                kind="ollama",
                model=model_id,
            )
        )
    return models


def get_model_info(model_id: str) -> ModelInfo:
    for model in available_models():
        if model.id == model_id:
            return model
    raise ValueError(f"unknown model id: {model_id!r}")
