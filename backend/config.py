"""Application settings loaded from the environment.

Every field can be overridden with ``STOCKROOM_<FIELD>``, notably
``STOCKROOM_DATABASE_URL``, ``STOCKROOM_ENVIRONMENT``, ``STOCKROOM_OPERATOR_NAME``,
``STOCKROOM_COMMIT``, ``STOCKROOM_BUILD_TIME`` and ``STOCKROOM_FRONTEND_DIST``.

The OTLP export settings keep their standard OpenTelemetry names
(``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_EXPORTER_OTLP_HEADERS``) so a stack can
be pointed at a collector without a Stockroom-specific variable; the
``STOCKROOM_`` spellings are accepted too, for ``.env`` files that keep every
knob in one namespace.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for one Stockroom deployment."""

    model_config = SettingsConfigDict(
        env_prefix="STOCKROOM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # The OTLP fields below have explicit aliases. Accept their field names
        # too, so a caller (or a test) can pass them as keyword arguments.
        populate_by_name=True,
    )

    app_name: str = "Stockroom"
    app_version: str = "0.1.0"
    database_url: str | None = None
    environment: str = "development"
    operator_name: str = "demo-operator"
    commit: str = "unknown"
    build_time: str = "unknown"
    # The Vite build output. It exists in the production image and after a local
    # `npm run build`; on a fresh clone it is absent and the SPA mount is skipped.
    frontend_dist: str = "frontend/dist"
    # OTLP/HTTP export (T6.1 / #55). Unset means "no exporter": the app still
    # traces, logs and counts, and exports nothing (AC8).
    otlp_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "STOCKROOM_OTLP_ENDPOINT",
        ),
    )
    otlp_headers: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OTEL_EXPORTER_OTLP_HEADERS",
            "STOCKROOM_OTLP_HEADERS",
        ),
    )
    telemetry_export_interval_millis: int = 5000
    telemetry_export_timeout_seconds: float = 3.0
    telemetry_drift_interval_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance, loaded once."""
    return Settings()
