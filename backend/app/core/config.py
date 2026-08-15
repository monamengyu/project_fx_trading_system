from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str
    app_name: str = "FX Trading System"
    market_data_cache_ttl_seconds: int = 3600
    # Browser origins allowed to call the API (the React dev server).
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


settings = Settings()
