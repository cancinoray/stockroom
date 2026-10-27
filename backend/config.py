"""Application settings loaded from the environment.

Every field can be overridden with ``STOCKROOM_<FIELD>``, notably
``STOCKROOM_ENVIRONMENT``, ``STOCKROOM_OPERATOR_NAME``, ``STOCKROOM_COMMIT`` and
``STOCKROOM_BUILD_TIME``.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for one Stockroom deployment."""

    model_config = SettingsConfigDict(
        env_prefix="STOCKROOM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Stockroom"
    app_version: str = "0.1.0"
    environment: str = "development"
    operator_name: str = "demo-operator"
    commit: str = "unknown"
    build_time: str = "unknown"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance, loaded once."""
    return Settings()
