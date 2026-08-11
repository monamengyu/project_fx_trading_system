from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str
    app_name: str = "FX Trading System"
    market_data_cache_ttl_seconds: int = 3600


settings = Settings()
