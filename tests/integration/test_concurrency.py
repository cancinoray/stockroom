"""US2 proven against a live server: contention cannot oversell or deadlock.

The claim in ``product-spec.md`` US2 and ``_docs/domain.md`` §5 is only credible
if the harness cannot serialise the requests. Every test here starts a real
``uvicorn`` process on an OS-assigned ephemeral port over its own freshly
migrated, seeded Postgres database, then releases requests together through a
``threading.Barrier``. ``TestClient`` is deliberately not used: an in-process
client can hide an ASGI-level serialisation and pass while production fails.

Two scenarios:

- 50 iterations of 20 simultaneous orders for the last available unit: exactly
  one ``201``, nineteen ``409``, ``reserved == 1`` and ``available == 0`` read
  from the database, with no status other than ``201``/``409`` in 1,000
  requests (US2-AC1, US2-AC2).
- 10 rounds of 10 simultaneous two-line orders, listed in opposite SKU order:
  four accepted, six rejected, every accepted order holding exactly one
  reservation per line and every rejected order leaving no row behind, with
  ``/api/invariants`` clean after each round (US2-AC3).

State is reset through the API only: the winning order is cancelled, which
writes the ``release`` movements itself. Nothing here updates a counter or a
movement directly, because the append-only ledger and the ordered row lock are
the behaviour under test (``AGENTS.md`` rules 1-3).

Each test owns its server, database and port, and asserts at shutdown that the
process exited, the port stopped listening and the database was dropped. The
server's stdout/stderr is captured to a temporary file and attached to the
failure when a test fails.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import psycopg
from sqlalchemy import Engine, bindparam, create_engine, text
from sqlalchemy.engine import make_url

from backend.db import seed as seed_module

REPO_ROOT = Path(__file__).resolve().parents[2]

WORKERS = 20
ITERATIONS = 50
# Seeded with three units on hand; the test adjusts it down to one.
LAST_UNIT_SKU = "SKU-8820"

PAIR_SKUS = ("SKU-1042", "SKU-3301")
PAIR_QTY = 4
PAIR_WORKERS = 10
PAIR_ROUNDS = 10
# SKU-1042 has 18 on hand and every order wants 4, so exactly four fit.
PAIR_ACCEPTED = 4

# Generous enough that a slow machine does not flake, short enough that a hang
# fails the test instead of blocking the suite. ``CALL_TIMEOUT`` exceeds the
# HTTP timeout so the client's own error is the one reported.
HTTP_TIMEOUT = 30.0
CALL_TIMEOUT = 60.0
SERVER_START_TIMEOUT = 30.0
SERVER_STOP_TIMEOUT = 10.0

# I2 / I3 from _docs/domain.md §4: the caches must equal the ledger.
STOCK_LEDGER_SQL = """
SELECT s.sku,
       s.on_hand            AS cached_on_hand,
       COALESCE(SUM(m.delta_on_hand), 0)  AS ledger_on_hand,
       s.reserved           AS cached_reserved,
       COALESCE(SUM(m.delta_reserved), 0) AS ledger_reserved
  FROM stock s
  LEFT JOIN movements m USING (warehouse_id, sku)
 GROUP BY s.warehouse_id, s.sku, s.on_hand, s.reserved
HAVING s.on_hand  <> COALESCE(SUM(m.delta_on_hand), 0)
    OR s.reserved <> COALESCE(SUM(m.delta_reserved), 0)
    OR s.reserved > s.on_hand
    OR s.on_hand < 0
    OR s.reserved < 0
"""

# I5 from _docs/domain.md §4: confirmed orders hold one reservation per line.
ORDER_RESERVATION_SQL = """
SELECT o.id, l.sku
  FROM orders o
  JOIN order_lines l ON l.order_id = o.id
  LEFT JOIN movements m
         ON m.order_id = o.id AND m.sku = l.sku AND m.reason = 'reserve'
 WHERE o.status = 'confirmed'
 GROUP BY o.id, l.sku, l.qty
HAVING COALESCE(SUM(m.delta_reserved), 0) <> l.qty
"""


# --------------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------------- #
# Copied from tests/integration/test_seed.py rather than imported: this module
# must own every helper it uses, and that module is not ours to change.


def _admin_dsn(session_url: str) -> str:
    """The same server as ``session_url``, connected to the maintenance database."""
    return (
        make_url(session_url)
        .set(drivername="postgresql", database="postgres")
        .render_as_string(hide_password=False)
    )


@contextmanager
def _fresh_database(session_url: str) -> Iterator[str]:
    """Create a database beside the session's disposable one, then drop it."""
    url = make_url(session_url)
    name = f"stockroom_concurrency_{uuid.uuid4().hex[:12]}"
    admin_dsn = _admin_dsn(session_url)

    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _database_exists(admin_dsn: str, name: str) -> bool:
    with psycopg.connect(admin_dsn, connect_timeout=5) as connection:
        row = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
    return row is not None


def _run_alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "STOCKROOM_DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


# --------------------------------------------------------------------------- #
# Live-server helpers
# --------------------------------------------------------------------------- #


def _free_port() -> int:
    """Ask the OS for an ephemeral port by binding port 0 and reading it back."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_accepts_connections(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _read_log(log_path: Path) -> str:
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - the log file is created by us
        return f"<could not read {log_path}: {exc}>"


def _stop_server(process: subprocess.Popen[str], log_path: Path) -> str:
    """Terminate the server and return everything it wrote.

    Called from a ``finally`` on every path, so a failing assertion cannot leave
    a stray uvicorn process or listener behind.
    """
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=SERVER_STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=SERVER_STOP_TIMEOUT)
    return _read_log(log_path)


def _report_server_output(output: str, exc: BaseException) -> None:
    """Attach the server log to a failing test without hiding the assertion."""
    if not output.strip():
        return
    print(f"\n--- uvicorn output ---\n{output}", file=sys.stderr)
    exc.add_note(f"uvicorn output:\n{output}")


def _wait_until_ready(
    process: subprocess.Popen[str],
    base_url: str,
    log_path: Path,
) -> None:
    deadline = time.monotonic() + SERVER_START_TIMEOUT
    with httpx.Client(trust_env=False, timeout=2.0) as http:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(
                    f"uvicorn exited before becoming ready:\n{_read_log(log_path)}"
                )
            try:
                if http.get(f"{base_url}/healthz").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    raise AssertionError(
        f"uvicorn did not answer /healthz within {SERVER_START_TIMEOUT}s:\n{_read_log(log_path)}"
    )


def _start_server(database_url: str, port: int) -> tuple[Path, subprocess.Popen[str]]:
    """Start ``uvicorn`` against ``database_url`` on ``port``.

    On any startup failure the process is stopped and its log raised, so a
    half-started server never escapes this call.
    """
    handle, log_name = tempfile.mkstemp(prefix="stockroom-uvicorn-", suffix=".log")
    log_path = Path(log_name)
    with os.fdopen(handle, "w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=REPO_ROOT,
            env={**os.environ, "STOCKROOM_DATABASE_URL": database_url},
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        _wait_until_ready(process, f"http://127.0.0.1:{port}", log_path)
    except BaseException:
        _stop_server(process, log_path)
        log_path.unlink(missing_ok=True)
        raise
    return log_path, process


def _assert_port_closed(port: int, timeout: float = SERVER_STOP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_accepts_connections(port):
            return
        time.sleep(0.05)
    raise AssertionError(f"127.0.0.1:{port} still accepts connections after uvicorn stopped")


@contextmanager
def _running_server(database_url: str) -> Iterator[SimpleNamespace]:
    """A live uvicorn on an ephemeral port, stopped in a ``finally``."""
    port = _free_port()
    log_path, process = _start_server(database_url, port)
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield SimpleNamespace(url=base_url, port=port, process=process)
    except BaseException as exc:
        _report_server_output(_stop_server(process, log_path), exc)
        raise
    else:
        _stop_server(process, log_path)
        assert process.poll() is not None, "uvicorn did not exit"
        _assert_port_closed(port)
    finally:
        log_path.unlink(missing_ok=True)


@contextmanager
def _live_stack(session_database_url: str) -> Iterator[SimpleNamespace]:
    """A fresh database at ``head``, seeded, with a live server against it."""
    with _fresh_database(session_database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        try:
            seed_module.seed(engine)
            with _running_server(url) as server:
                yield SimpleNamespace(
                    base_url=server.url,
                    port=server.port,
                    process=server.process,
                    database_url=url,
                    engine=engine,
                )
        finally:
            engine.dispose()


# --------------------------------------------------------------------------- #
# HTTP and assertion helpers
# --------------------------------------------------------------------------- #


@contextmanager
def _clients(base_url: str, count: int) -> Iterator[list[httpx.Client]]:
    """One client per worker, closed even when the test fails."""
    workers = [
        httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(HTTP_TIMEOUT),
            trust_env=False,
        )
        for _ in range(count)
    ]
    try:
        yield workers
    finally:
        for client in workers:
            client.close()


def _post_together(
    clients: list[httpx.Client],
    payloads: list[dict],
) -> list[httpx.Response]:
    """Release every POST at the same barrier and collect the responses.

    A barrier timeout, connection reset, read timeout or any other transport
    error propagates out of ``future.result`` and fails the test: US2-AC2
    requires that none of those happen under contention.
    """
    barrier = threading.Barrier(len(payloads))

    def submit(index: int) -> httpx.Response:
        client = clients[index]
        barrier.wait(timeout=CALL_TIMEOUT)
        return client.post("/api/orders", json=payloads[index])

    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        futures = [pool.submit(submit, index) for index in range(len(payloads))]
        return [future.result(timeout=CALL_TIMEOUT) for future in futures]


def _split_statuses(
    responses: list[httpx.Response],
    *,
    context: str,
) -> tuple[list[httpx.Response], list[httpx.Response]]:
    """Split 201s from 409s and fail on anything else, 500s included."""
    unexpected = [
        (response.status_code, response.text[:300])
        for response in responses
        if response.status_code not in (201, 409)
    ]
    assert not unexpected, f"{context}: only 201 and 409 are allowed, got {unexpected}"
    accepted = [response for response in responses if response.status_code == 201]
    rejected = [response for response in responses if response.status_code == 409]
    return accepted, rejected


def _assert_insufficient_stock(
    response: httpx.Response,
    *,
    short_skus: set[str],
) -> dict:
    """Every rejection is a problem+json insufficient_stock with a trace id."""
    assert response.status_code == 409
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("application/problem+json"), content_type
    body = response.json()
    assert body["type"] == "insufficient_stock", body
    assert body["status"] == 409, body
    trace_id = body.get("trace_id")
    assert isinstance(trace_id, str) and trace_id.strip(), body
    errors = body.get("errors")
    assert errors, body
    assert all(error["short_by"] >= 1 for error in errors), errors
    assert {error["sku"] for error in errors} == short_skus, errors
    return body


def _cancel_order(http: httpx.Client, order_id: str) -> None:
    """Cancel through the API, which writes the release movements."""
    response = http.post(f"/api/orders/{order_id}/cancel")
    assert response.status_code == 200, f"cancel {order_id}: {response.status_code} {response.text}"
    document = response.json()
    assert document["id"] == order_id
    assert document["status"] == "cancelled"


def _release_confirmed_orders(http: httpx.Client) -> None:
    """Reset reservations through the API: cancel everything still confirmed."""
    response = http.get("/api/orders")
    assert response.status_code == 200, response.text
    for order in response.json():
        if order["status"] == "confirmed":
            _cancel_order(http, order["id"])


def _stock_row(http: httpx.Client, sku: str) -> dict:
    response = http.get("/api/stock")
    assert response.status_code == 200, response.text
    for row in response.json():
        if row["sku"] == sku:
            return row
    raise AssertionError(f"{sku} is not in GET /api/stock")


def _stock_counts(engine: Engine, sku: str) -> tuple[int, int, int]:
    """``(on_hand, reserved, available)`` read from the database, not the API."""
    with engine.connect() as connection:
        on_hand, reserved = connection.execute(
            text("SELECT on_hand, reserved FROM stock WHERE sku = :sku"),
            {"sku": sku},
        ).one()
    return on_hand, reserved, on_hand - reserved


def _scalar(engine: Engine, sql: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


def _assert_invariants(engine: Engine, http: httpx.Client, *, context: str) -> None:
    """The documented checks and the endpoint agree: nothing is drifting."""
    with engine.connect() as connection:
        stock_violations = connection.execute(text(STOCK_LEDGER_SQL)).all()
        order_violations = connection.execute(text(ORDER_RESERVATION_SQL)).all()
    assert stock_violations == [], f"{context}: I2/I3 violations {stock_violations}"
    assert order_violations == [], f"{context}: I5 violations {order_violations}"

    response = http.get("/api/invariants")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["ok"] is True, f"{context}: {report}"
    assert report["violations"] == [], f"{context}: {report}"


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_fifty_iterations_of_twenty_way_contention_for_the_last_unit(
    database_url: str,
) -> None:
    """US2-AC1 / US2-AC2: one winner per iteration, 1,000 requests, no 500s."""
    with _live_stack(database_url) as stack, _clients(stack.base_url, WORKERS) as clients:
        control = clients[0]

        # Leave exactly one available unit through the API; never touch counters.
        stock = _stock_row(control, LAST_UNIT_SKU)
        delta = 1 - stock["available"]
        assert delta != 0, f"seed must leave more than one unit available: {stock}"
        adjusted = control.post(
            "/api/stock/adjust",
            json={
                "sku": LAST_UNIT_SKU,
                "delta": delta,
                "note": "Concurrency proof: leave the last unit",
            },
        )
        assert adjusted.status_code == 201, adjusted.text
        assert adjusted.json()["available"] == 1, adjusted.json()

        totals = {201: 0, 409: 0}
        for iteration in range(ITERATIONS):
            payloads = [
                {
                    "customer_ref": f"last-{iteration:02d}-{worker:02d}",
                    "lines": [{"sku": LAST_UNIT_SKU, "qty": 1}],
                }
                for worker in range(WORKERS)
            ]
            responses = _post_together(clients, payloads)
            accepted, rejected = _split_statuses(
                responses, context=f"iteration {iteration} of {ITERATIONS}"
            )

            assert len(accepted) == 1, (
                f"iteration {iteration}: {len(accepted)} orders won the last unit; "
                f"statuses {[response.status_code for response in responses]}"
            )
            assert len(rejected) == WORKERS - 1, f"iteration {iteration}: {len(rejected)} 409s"
            for response in rejected:
                _assert_insufficient_stock(response, short_skus={LAST_UNIT_SKU})

            # US2-AC1: the database, not the response body, says what is held.
            counts = _stock_counts(stack.engine, LAST_UNIT_SKU)
            assert counts == (1, 1, 0), f"iteration {iteration}: {LAST_UNIT_SKU} is {counts}"

            totals[201] += len(accepted)
            totals[409] += len(rejected)

            # Reset through the API only: the release movement frees the unit.
            _cancel_order(control, accepted[0].json()["id"])
            assert _stock_counts(stack.engine, LAST_UNIT_SKU) == (1, 0, 1), (
                f"iteration {iteration}: reservation was not released"
            )

        # US2-AC2: across all 1,000 requests the only statuses were 201 and 409.
        assert totals == {201: ITERATIONS, 409: ITERATIONS * (WORKERS - 1)}, totals
        assert _scalar(stack.engine, "SELECT count(*) FROM orders") == ITERATIONS
        assert (
            _scalar(stack.engine, "SELECT count(*) FROM movements WHERE reason = 'reserve'")
            == ITERATIONS
        )
        assert (
            _scalar(stack.engine, "SELECT count(*) FROM movements WHERE reason = 'release'")
            == ITERATIONS
        )
        _assert_invariants(stack.engine, control, context="after 50 iterations")


def test_opposing_line_order_cannot_deadlock_or_leave_a_half_reserved_order(
    database_url: str,
) -> None:
    """US2-AC3: 10 rounds of 10 two-line orders, both line orders interleaved."""
    with _live_stack(database_url) as stack, _clients(stack.base_url, PAIR_WORKERS) as clients:
        control = clients[0]

        for round_index in range(PAIR_ROUNDS):
            # Reset through the API first: release whatever the last round held.
            _release_confirmed_orders(control)
            assert _stock_counts(stack.engine, PAIR_SKUS[0]) == (18, 0, 18)
            assert _stock_counts(stack.engine, PAIR_SKUS[1]) == (40, 0, 40)

            # Half the orders list SKU-1042 first, half SKU-3301 first, so a
            # non-ordered lock acquisition would form a wait-for cycle.
            payloads = []
            for worker in range(PAIR_WORKERS):
                skus = PAIR_SKUS if worker % 2 == 0 else tuple(reversed(PAIR_SKUS))
                payloads.append(
                    {
                        "customer_ref": f"pair-{round_index:02d}-{worker:02d}",
                        "lines": [{"sku": sku, "qty": PAIR_QTY} for sku in skus],
                    }
                )

            responses = _post_together(clients, payloads)
            accepted, rejected = _split_statuses(
                responses, context=f"round {round_index} of {PAIR_ROUNDS}"
            )

            assert len(accepted) == PAIR_ACCEPTED, (
                f"round {round_index}: {len(accepted)} orders accepted; "
                f"statuses {[response.status_code for response in responses]}"
            )
            assert len(rejected) == PAIR_WORKERS - PAIR_ACCEPTED
            for response in rejected:
                _assert_insufficient_stock(response, short_skus={PAIR_SKUS[0]})

            accepted_ids = [response.json()["id"] for response in accepted]
            rejected_refs = [
                payloads[index]["customer_ref"]
                for index, response in enumerate(responses)
                if response.status_code == 409
            ]
            expected_lines = {sku: (PAIR_QTY, 1, PAIR_QTY) for sku in PAIR_SKUS}

            with stack.engine.connect() as connection:
                for order_id in accepted_ids:
                    # Accepted: both lines, one reserve movement per line, right size.
                    order = connection.execute(
                        text("SELECT id, status FROM orders WHERE id = :id"),
                        {"id": order_id},
                    ).one_or_none()
                    assert order is not None, f"round {round_index}: order {order_id} vanished"
                    assert order.status == "confirmed"

                    rows = connection.execute(
                        text(
                            "SELECT l.sku, l.qty, count(m.id) AS movements, "
                            "       COALESCE(SUM(m.delta_reserved), 0) AS reserved "
                            "  FROM order_lines l "
                            "  LEFT JOIN movements m "
                            "         ON m.order_id = l.order_id AND m.sku = l.sku "
                            "        AND m.reason = 'reserve' "
                            " WHERE l.order_id = :order_id "
                            " GROUP BY l.sku, l.qty"
                        ),
                        {"order_id": order_id},
                    ).all()
                    held = {row.sku: (row.qty, row.movements, row.reserved) for row in rows}
                    assert held == expected_lines, f"round {round_index}: {order_id} holds {held}"

                # Rejected: no order row and therefore no movement.
                rejected_orders = connection.execute(
                    text(
                        "SELECT id, customer_ref FROM orders WHERE customer_ref IN :refs"
                    ).bindparams(bindparam("refs", expanding=True)),
                    {"refs": rejected_refs},
                ).all()
                rejected_movements = connection.execute(
                    text(
                        "SELECT count(*) FROM movements m "
                        "  JOIN orders o ON o.id = m.order_id "
                        " WHERE o.customer_ref IN :refs"
                    ).bindparams(bindparam("refs", expanding=True)),
                    {"refs": rejected_refs},
                ).scalar_one()

            assert rejected_orders == [], f"round {round_index}: {rejected_orders}"
            assert rejected_movements == 0, f"round {round_index}: {rejected_movements}"

            # The split is asserted, not assumed: four winners hold both SKUs.
            assert _stock_counts(stack.engine, PAIR_SKUS[0]) == (18, 16, 2)
            assert _stock_counts(stack.engine, PAIR_SKUS[1]) == (40, 16, 24)
            expected_orders = PAIR_ACCEPTED * (round_index + 1)
            assert _scalar(stack.engine, "SELECT count(*) FROM orders") == expected_orders
            assert _scalar(
                stack.engine,
                "SELECT count(*) FROM movements WHERE reason = 'reserve'",
            ) == expected_orders * len(PAIR_SKUS)

            _assert_invariants(stack.engine, control, context=f"round {round_index}")

        # Leave the stack clean through the API and prove the release path held.
        _release_confirmed_orders(control)
        assert _stock_counts(stack.engine, PAIR_SKUS[0]) == (18, 0, 18)
        assert _stock_counts(stack.engine, PAIR_SKUS[1]) == (40, 0, 40)
        _assert_invariants(stack.engine, control, context="after the last round")


def test_the_stack_leaves_no_stray_process_port_or_database(database_url: str) -> None:
    """The cleanup AC: terminating the test kills the server, port and database."""
    admin_dsn = _admin_dsn(database_url)

    with _live_stack(database_url) as stack:
        process = stack.process
        port = stack.port
        database_name = make_url(stack.database_url).database
        assert database_name is not None

        with httpx.Client(trust_env=False, timeout=HTTP_TIMEOUT) as http:
            assert http.get(f"{stack.base_url}/healthz").status_code == 200
        assert process.poll() is None, "the server should be running inside the test"
        assert _port_accepts_connections(port), "the server should be listening inside the test"
        assert _database_exists(admin_dsn, database_name)

    assert process.poll() is not None, "uvicorn is still running after the test"
    assert not _port_accepts_connections(port), f"port {port} is still listening"
    assert not _database_exists(admin_dsn, database_name), f"{database_name} was not dropped"
