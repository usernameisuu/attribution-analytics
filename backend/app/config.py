from functools import lru_cache
from decimal import Decimal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATTRIBUTION_", extra="ignore")
    database_url: str
    public_origin: str = "http://localhost:8080"
    additional_public_origins: list[str] = Field(default_factory=list)
    secure_cookie: bool = True
    session_hours: int = 8
    deepseek_key: SecretStr | None = Field(default=None, validation_alias='DEEPSEEK_API_KEY')
    deepseek_model: str = Field(default='deepseek-flash', validation_alias='DEEPSEEK_MODEL')
    model_input_cny_per_million: Decimal = Decimal('0')
    model_output_cny_per_million: Decimal = Decimal('0')
    model_price_verified_on: str = ''


@lru_cache
def settings() -> Settings:
    return Settings()
