from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env regardless of the process working directory
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_BACKEND_DIR / ".env")

    database_url: str
    app_name: str = "FX Trading System"
    market_data_cache_ttl_seconds: int = 3600
    # Browser origins allowed to call the API (the React dev server).
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # NL trade parsing
    nl_parse_default_model: str = "rule-based"
    # A single OpenRouter API key enables all hosted LLM models in the dropdown.
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter model IDs offered in the NL parse dropdown (JSON list in .env)
    openrouter_models: list[str] = [
        "openai/gpt-5.6-luna",
        "anthropic/claude-sonnet-5",
        "google/gemini-3.8-flash",
        "deepseek/deepseek-v4-flash-0731",
        "z-ai/glm-5.3-flash",
    ]
    ollama_base_url: str = "http://localhost:11434/v1"
    # Local Ollama model IDs offered in the NL parse dropdown (JSON list in .env)
    ollama_models: list[str] = ["llama3.2:3b", "qwen2.5:3b", "gemma2:2b", "phi3.5"]
    # Generous timeout: cold-loading a large local model (e.g. phi3.5) on CPU
    # can take ~80s before the first token arrives.
    llm_request_timeout_seconds: int = 120


settings = Settings()
