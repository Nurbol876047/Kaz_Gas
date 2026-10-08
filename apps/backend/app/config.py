from functools import lru_cache
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    bot_token: str = ""
    bot_api_key: str = Field(min_length=32)
    allowed_origins: str = "https://localhost"
    cookie_secure: bool = True
    environment: str = "production"
    upload_dir: Path = Path("/data/uploads")
    max_photo_bytes: int = 10 * 1024 * 1024
    session_hours: int = 8
    timezone: str = "Asia/Qyzylorda"
    gemini_api_key: str = ""

    @field_validator("database_url")
    @classmethod
    def use_asyncpg_driver(cls, value: str) -> str:
        # Managed Postgres providers (Render, etc.) hand out plain postgres://
        # or postgresql:// URLs; the async engine requires the asyncpg driver.
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://"):]
        return value

    @property
    def origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.allowed_origins.split(",")]

    @model_validator(mode="after")
    def production_security(self):
        if self.environment == "production" and (
            not self.cookie_secure or any(not x.startswith("https://") for x in self.origins)
        ):
            raise ValueError("Production requires HTTPS origins and secure cookies")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
