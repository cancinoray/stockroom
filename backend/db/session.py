"""Database engine, session factory and the health probe.

The engine is cached per URL, so pointing ``STOCKROOM_DATABASE_URL`` at a
different database (as the integration tests do) yields a fresh engine.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from functools import lru_cache
from typing import Literal

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings

logger = logging.getLogger(__name__)

DatabaseStatus = Literal["ok", "unreachable", "not_configured"]


@lru_cache(maxsize=8)
def engine_for(database_url: str) -> Engine:
    """Return a cached engine for ``database_url``."""
    return create_engine(database_url, pool_pre_ping=True)


def get_engine() -> Engine:
    """Return the engine for the configured database."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("STOCKROOM_DATABASE_URL is not configured")
    return engine_for(database_url)


def get_sessionmaker() -> sessionmaker[Session]:
    """Return a session factory bound to the configured database."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a short-lived session."""
    with get_sessionmaker()() as session:
        yield session


def probe_database() -> DatabaseStatus:
    """Check that the configured database answers a trivial query.

    ``not_configured`` preserves the walking-skeleton response from #1. A
    failed connection is logged (without the DSN) and reported as
    ``unreachable``; it is never swallowed silently.
    """
    database_url = get_settings().database_url
    if not database_url:
        return "not_configured"

    try:
        with engine_for(database_url).connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("Database health probe failed", exc_info=True)
        return "unreachable"

    return "ok"
