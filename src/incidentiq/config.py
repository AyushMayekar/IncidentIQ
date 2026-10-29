import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str | None:
    """Path to the settings file, overridable so tests never read the real ``.env``."""
    return os.environ.get("INCIDENTIQ_ENV_FILE", ".env")


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()