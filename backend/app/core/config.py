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
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    # Anthropic model IDs offered in the NL parse dropdown (JSON list in .env)
    anthropic_models: list[str] = [
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-5",
        "claude-opus-4-5",
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
    ]
    ollama_base_url: str = "http://localhost:11434/v1"
    llm_request_timeout_seconds: int = 30


settings = Settings()
