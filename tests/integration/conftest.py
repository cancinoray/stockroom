"""Integration-test harness: a disposable PostgreSQL 16 per test session.

By default the suite starts its own ``postgres:16`` container, moves it to an
ephemeral loopback port, and removes it when the session ends. Set
``STOCKROOM_TEST_DATABASE_URL`` to reuse an existing database instead; that
database is assumed to be empty and disposable, because the migration-cycle
test downgrades it to ``base`` and the suite runs migrations against it. Never
point the override at a shared or production database.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import Engine, create_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_IMAGE = "postgres:16"
CONTAINER_USER = "stockroom"
CONTAINER_PASSWORD = "stockroom"
CONTAINER_DB = "stockroom_test"


def _docker_is_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True, text=True).returncode == 0


def _start_postgres() -> tuple[str, str]:
    """Start a throwaway Postgres 16 container and return ``(name, url)``."""
    name = f"stockroom-test-{uuid.uuid4().hex[:12]}"
    started = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-e",
            f"POSTGRES_USER={CONTAINER_USER}",
            "-e",
            f"POSTGRES_PASSWORD={CONTAINER_PASSWORD}",
            "-e",
            f"POSTGRES_DB={CONTAINER_DB}",
            "-p",
            "127.0.0.1::5432",
            CONTAINER_IMAGE,
        ],
        capture_output=True,
        text=True,
    )
    if started.returncode != 0:
        raise RuntimeError(
            "Could not start the disposable Postgres container. "
            "Set STOCKROOM_TEST_DATABASE_URL to an empty disposable database instead.\n"
            f"{started.stderr}"
        )

    published = subprocess.run(
        ["docker", "port", name, "5432/tcp"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    port = published.rsplit(":", 1)[1]
    url = (
        f"postgresql+psycopg://{CONTAINER_USER}:{CONTAINER_PASSWORD}"
        f"@127.0.0.1:{port}/{CONTAINER_DB}"
    )
    return name, url


def _wait_until_ready(url: str, timeout: float = 90.0) -> None:
    dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as connection:
                connection.execute("SELECT 1")
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(0.5)
        else:
            return
    raise RuntimeError(f"Postgres did not become ready within {timeout}s: {last_error}")


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """URL of a disposable, empty Postgres 16 database owned by this session."""
    override = os.environ.get("STOCKROOM_TEST_DATABASE_URL")
    if override:
        _wait_until_ready(override)
        yield override
        return

    if not _docker_is_available():
        raise RuntimeError(
            "Docker is not reachable and STOCKROOM_TEST_DATABASE_URL is unset. "
            "Start Docker, or point the override at an empty disposable database."
        )

    name, url = _start_postgres()
    try:
        _wait_until_ready(url)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    """SQLAlchemy engine for the disposable database."""
    db_engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield db_engine
    finally:
        db_engine.dispose()


@pytest.fixture(scope="session")
def run_alembic(database_url: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run Alembic against the disposable database and fail loudly on error."""

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO_ROOT,
            env={**os.environ, "STOCKROOM_DATABASE_URL": database_url},
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"alembic {' '.join(args)} failed\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    return run


@pytest.fixture(scope="session")
def migrated_database(
    database_url: str,
    run_alembic: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    """The disposable database with the schema at ``head``."""
    run_alembic("upgrade", "head")
    return database_url
