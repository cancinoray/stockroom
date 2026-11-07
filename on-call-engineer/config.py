"""Configuration for the alert poller and evidence collector (T7.1, issue #61).

Every base URL and bound comes from the environment, with the non-secret local
defaults documented in ``.env.example``. There are no credentials here and
there is nothing to discover: the collector only talks to the three local
services whose URLs this module validates.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PROMETHEUS_URL = "http://localhost:9090"
DEFAULT_LOKI_URL = "http://localhost:3100"
DEFAULT_APP_URL = "http://localhost:8000"
DEFAULT_POLL_INTERVAL_SECONDS = 60
DEFAULT_LOOKBACK_MINUTES = 15
DEFAULT_LOG_SAMPLES = 20
DEFAULT_TRACE_SAMPLES = 3
DEFAULT_HTTP_TIMEOUT_SECONDS = 5.0
DEFAULT_EVIDENCE_DIR = "on-call-engineer/evidence"
DEFAULT_STATE_DIR = "on-call-engineer/.state"
DEFAULT_RESOLVE_GRACE_POLLS = 2
DEFAULT_BASE_REF = "main"
DEFAULT_IMAGE_REFERENCE = "stockroom-app:local"

# The local stack is the only permitted target. The collector is read-only and
# credential-free, and this guard keeps a stray environment variable from
# pointing it at a remote host that would need credentials.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_URL_SETTINGS = (
    ("PROMETHEUS_URL", "prometheus_url"),
    ("LOKI_URL", "loki_url"),
    ("STOCKROOM_APP_URL", "app_url"),
)


class ConfigError(ValueError):
    """An environment value the poller refuses to run with."""


@dataclass(frozen=True, slots=True)
class Config:
    """The resolved settings for one poller process."""

    prometheus_url: str = DEFAULT_PROMETHEUS_URL
    loki_url: str = DEFAULT_LOKI_URL
    app_url: str = DEFAULT_APP_URL
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES
    log_samples: int = DEFAULT_LOG_SAMPLES
    trace_samples: int = DEFAULT_TRACE_SAMPLES
    http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS
    evidence_dir: Path = Path(DEFAULT_EVIDENCE_DIR)
    state_dir: Path = Path(DEFAULT_STATE_DIR)
    resolve_grace_polls: int = DEFAULT_RESOLVE_GRACE_POLLS
    base_ref: str = DEFAULT_BASE_REF
    base_commit: str | None = None
    repo_source: str = "poller_checkout"
    image_reference: str = DEFAULT_IMAGE_REFERENCE

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        cwd: Path | None = None,
    ) -> Config:
        """Read the documented variables, validate them and resolve paths."""
        settings = os.environ if environ is None else environ
        root = Path.cwd() if cwd is None else cwd
        base_commit, repo_source = _base_commit(settings, root)

        config = cls(
            prometheus_url=_url(settings, "PROMETHEUS_URL", DEFAULT_PROMETHEUS_URL),
            loki_url=_url(settings, "LOKI_URL", DEFAULT_LOKI_URL),
            app_url=_url(settings, "STOCKROOM_APP_URL", DEFAULT_APP_URL),
            poll_interval_seconds=_integer(
                settings, "ONCALL_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS, minimum=1
            ),
            lookback_minutes=_integer(
                settings, "ONCALL_LOOKBACK_MINUTES", DEFAULT_LOOKBACK_MINUTES, minimum=1
            ),
            log_samples=_integer(settings, "ONCALL_LOG_SAMPLES", DEFAULT_LOG_SAMPLES, minimum=0),
            trace_samples=_integer(
                settings, "ONCALL_TRACE_SAMPLES", DEFAULT_TRACE_SAMPLES, minimum=0
            ),
            http_timeout_seconds=_number(
                settings, "ONCALL_HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT_SECONDS
            ),
            evidence_dir=_path(settings, "ONCALL_EVIDENCE_DIR", DEFAULT_EVIDENCE_DIR, root),
            state_dir=_path(settings, "ONCALL_STATE_DIR", DEFAULT_STATE_DIR, root),
            resolve_grace_polls=_integer(
                settings, "ONCALL_RESOLVE_GRACE_POLLS", DEFAULT_RESOLVE_GRACE_POLLS, minimum=0
            ),
            base_ref=_text(settings, "ONCALL_BASE_REF", DEFAULT_BASE_REF),
            base_commit=base_commit,
            repo_source=repo_source,
            image_reference=_text(settings, "STOCKROOM_IMAGE", DEFAULT_IMAGE_REFERENCE),
        )
        config.validate_local()
        return config

    def validate_local(self) -> None:
        """Refuse anything that is not one of the three local HTTP endpoints."""
        for name, attribute in _URL_SETTINGS:
            _validate_url(name, getattr(self, attribute))


def _text(settings: Mapping[str, str], name: str, default: str) -> str:
    value = settings.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _integer(settings: Mapping[str, str], name: str, default: int, *, minimum: int) -> int:
    raw = settings.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    return value


def _number(settings: Mapping[str, str], name: str, default: float) -> float:
    raw = settings.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return value


def _path(settings: Mapping[str, str], name: str, default: str, root: Path) -> Path:
    raw = _text(settings, name, default)
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def _url(settings: Mapping[str, str], name: str, default: str) -> str:
    return _text(settings, name, default).rstrip("/")


def _base_commit(settings: Mapping[str, str], root: Path) -> tuple[str | None, str]:
    """The declared commit and whether it came from the operator or the checkout.

    ``None`` means the commit could not be observed; the packet records ``null``
    and T7.2 escalates instead of guessing a commit that was never seen.
    """
    declared = settings.get("ONCALL_BASE_COMMIT")
    if declared is not None and declared.strip():
        return declared.strip(), "operator"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "poller_checkout"
    commit = result.stdout.strip()
    if result.returncode == 0 and commit:
        return commit, "poller_checkout"
    return None, "poller_checkout"


def _validate_url(name: str, value: str) -> None:
    parts = urlsplit(value)
    # The error never repeats the value: a mistyped URL can carry userinfo.
    if parts.scheme not in {"http", "https"}:
        raise ConfigError(f"{name} must be an http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ConfigError(f"{name} must not contain credentials")
    if parts.hostname not in LOCAL_HOSTS:
        raise ConfigError(f"{name} must point at the local stack (localhost, 127.0.0.1 or ::1)")
    if parts.query or parts.fragment:
        raise ConfigError(f"{name} must not carry a query or fragment")
