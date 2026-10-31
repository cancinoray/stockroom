"""The migration chain works on an empty database, forwards and backwards."""

from __future__ import annotations

from collections.abc import Callable
from subprocess import CompletedProcess

from sqlalchemy import Engine, text


def test_upgrade_downgrade_upgrade_cycle(
    run_alembic: Callable[..., CompletedProcess[str]],
    engine: Engine,
) -> None:
    run_alembic("downgrade", "base")
    run_alembic("upgrade", "head")

    run_alembic("downgrade", "-1")

    with engine.connect() as connection:
        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    assert version is None

    run_alembic("upgrade", "head")

    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            ).scalars()
        )

    assert version == "0001_schema_constraints"
    assert {
        "products",
        "warehouses",
        "stock",
        "orders",
        "order_lines",
        "movements",
        "alembic_version",
    } <= tables
