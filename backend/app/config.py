from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATTRIBUTION_", extra="ignore")
    database_url: str
    public_origin: str = "http://localhost:8080"
    secure_cookie: bool = True
    session_hours: int = 8


@lru_cache
def settings() -> Settings:
    return Settings()
