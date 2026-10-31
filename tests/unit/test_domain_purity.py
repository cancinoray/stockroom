"""The domain package must stay pure: no ORM session, no HTTP client.

Purity is what makes these rules testable without a database. This test reads the
package source so a future import cannot quietly break the constraint.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[2] / "backend" / "domain"

FORBIDDEN_ROOTS = {
    "fastapi",
    "httpx",
    "psycopg",
    "psycopg2",
    "pydantic",
    "requests",
    "sqlalchemy",
    "starlette",
}
FORBIDDEN_LOCAL = {"backend.api", "backend.config", "backend.db", "backend.main"}


def imported_modules(path: Path) -> Iterator[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_the_domain_package_exists() -> None:
    assert DOMAIN.is_dir()
    assert sorted(path.name for path in DOMAIN.glob("*.py"))


def test_domain_imports_no_orm_or_http_library() -> None:
    offenders = []
    for path in sorted(DOMAIN.glob("*.py")):
        for module in imported_modules(path):
            root = module.split(".")[0]
            is_forbidden = root in FORBIDDEN_ROOTS or any(
                module == local or module.startswith(f"{local}.") for local in FORBIDDEN_LOCAL
            )
            if is_forbidden:
                offenders.append(f"{path.name}: {module}")

    assert offenders == []
