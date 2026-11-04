# Testing Guidelines

Which suite owns which claim, and how to run it. Behaviour is defined in
[product-spec.md](../product-spec.md) §6; this document only says where the proof lives.

The split follows one rule: **a test sits in the cheapest suite whose environment can still make it
fail.** A rule that is pure goes in `unit`, because a database would only slow it down. A claim
about SQL, locking or the HTTP contract cannot be proved without Postgres, so it goes in
`integration`. A claim about a person using the screen goes in `e2e`.

## 1. The three suites

| Suite         | Directory            | Command                 | May touch                                        | Prerequisites                                                                                                               |
| ------------- | -------------------- | ----------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `unit`        | `tests/unit/`        | `make test-unit`        | Python objects only                              | `make install` once (backend deps). No database, no server, no network.                                                     |
| `integration` | `tests/integration/` | `make test-integration` | The app, a real PostgreSQL 16 and the migrations | `make install`; Docker reachable, or `STOCKROOM_TEST_DATABASE_URL` pointing at an **empty, disposable** psycopg 3 database. |
| `e2e`         | `tests/e2e/`         | `make e2e`              | A running, migrated, seeded stack and a browser  | `make dev` (app on `:8000` + Postgres), and Playwright with its browsers installed.                                         |

`make test-unit` runs `uv run pytest tests/unit`; `pyproject.toml` also sets `testpaths = ["tests/unit"]`,
so a bare `uv run pytest` is the same suite. The integration harness starts its own throwaway
`postgres:16` container per session unless `STOCKROOM_TEST_DATABASE_URL` is set, and runs
`alembic upgrade head` against it — never point that variable at a shared or production database,
because the suite downgrades it to `base`. Integration tests seed through `backend.db.seed` and call
the app in-process, so no `make dev` is needed for them.

`make e2e` arrives with T4.4 together with `tests/e2e/` and the Playwright dependency; until that
lands the target does not exist. `make test` is `make test-unit` + `make test-frontend`
(Vitest, `frontend/`), which is what the pre-PR gate runs.

`make lint` is not a test suite but gates the same PR: `ruff check`, `ruff format --check`, `tsc -b`
and `eslint`. It needs both halves of `make install` — a backend-only install makes the frontend
half fail with `tsc: command not found`.

## 2. What the tags mean

`product-spec.md` §6 tags every acceptance criterion with where its proof belongs:

- **`unit`** — domain logic, database-free. Pure functions, value objects, the state machine, the
  validation seams in `backend/api/schemas.py` and `backend/api/stock.py`. If a test in this suite
  needs a session, a test client or a port, it is in the wrong suite.
- **`integration`** — HTTP plus a real Postgres. Proves SQL, constraints, triggers, transactions,
  locking, status codes and the error envelope. Runs the real migrations.
- **`e2e`** — Playwright against a running stack. Proves the operator can complete a task through
  the UI. Never used to re-prove a rule that `unit` or `integration` already owns.

Two tags on one AC (`unit` + `integration`) mean both must exist: the unit test pins the pure rule,
the integration test pins that the rule is wired to the database or the wire format. The tag is a
floor, not a ceiling — a `unit` claim may also have an integration test, but the reverse does not
make a `unit` claim true.

## 3. Which suite owns which claim

| AC                                    | Owner                  | Test that owns it                                                                                                                                                                     |
| ------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| US1-AC1 short line rejects the order  | `integration`          | `test_orders_qa.py::test_short_line_leaves_the_other_skus_reserved_unchanged`, `test_orders.py::test_reserve_rejects_a_short_line_and_reserves_nothing`                               |
| US1-AC2 every line reserves           | `integration`          | `test_orders.py::test_reserve_successful_order_reserves_every_line`                                                                                                                   |
| US1-AC3 prices are snapshotted        | `unit` (no seam yet)   | `test_orders_qa.py::test_price_snapshot_survives_a_later_catalogue_change` — see §5                                                                                                   |
| US1-AC4 invalid quantities            | `unit` + `integration` | `test_domain_ledger.py::test_a_non_positive_quantity_is_rejected`, `test_api_request_validation.py`, `test_orders.py::test_invalid_quantity_is_rejected_with_422`                     |
| US1-AC5 unknown SKU is a client error | `integration`          | `test_orders.py::test_reserve_unknown_sku_is_a_client_error`                                                                                                                          |
| US2-AC1..AC3 concurrency              | `integration`          | `test_concurrency.py` (T4.3 / #40); on this branch only AC3 is proved, by `test_orders_qa.py::test_ten_concurrent_multiline_orders_leave_no_partial_reservation` — see the note below |
| US3-AC1 cancel releases               | `integration`          | `test_orders.py::test_cancel_releases_every_line_and_leaves_on_hand`                                                                                                                  |
| US3-AC2 repeated cancel is refused    | `unit` + `integration` | `test_domain_orders.py::test_cancelling_an_already_cancelled_order_is_rejected`, `test_orders_lifecycle_qa.py::test_double_cancel_is_409_and_changes_no_counter_or_ledger`            |
| US3-AC3 fulfilled cannot be cancelled | `integration`          | `test_orders.py::test_cancel_a_fulfilled_order_is_409_and_changes_no_stock`                                                                                                           |
| US4-AC1 fulfil moves both counters    | `integration`          | `test_orders.py::test_fulfil_ships_both_counters_for_every_line`                                                                                                                      |
| US4-AC2 availability is unchanged     | `unit`                 | `test_domain_stock.py::test_fulfilment_leaves_availability_unchanged` and `..._for_every_line`                                                                                        |
| US4-AC3 cancelled cannot be fulfilled | `unit`                 | `test_domain_orders.py::test_a_cancelled_order_cannot_be_fulfilled`                                                                                                                   |
| US5-AC1 receive increases on-hand     | `integration`          | `test_stock.py::test_receive_increases_on_hand_and_available_and_writes_one_movement`                                                                                                 |
| US5-AC2 adjust cannot breach reserved | `integration`          | `test_stock_qa.py::test_adjust_below_reserved_is_rejected_without_any_write`                                                                                                          |
| US5-AC3 adjust cannot go negative     | `integration`          | `test_stock_qa.py::test_adjust_to_exactly_zero_is_allowed_and_below_zero_is_rejected`                                                                                                 |
| US5-AC4 reason and note rules         | `unit`                 | `test_api_request_validation.py`, `test_domain_ledger.py::test_movement_reasons_are_the_database_check_values`                                                                        |
| US5-AC5 no mutation endpoints         | `integration`          | `test_stock.py::test_movements_expose_no_mutation_endpoint`                                                                                                                           |
| US6-AC1 low stock vs reorder point    | `unit` + `e2e`         | `test_domain_stock.py::test_low_stock_compares_available_with_the_reorder_point`; the `e2e` half lands with T4.4                                                                      |
| US6-AC2 audit trail                   | `integration`          | `test_stock.py::test_movements_are_newest_first_with_a_running_on_hand_balance`                                                                                                       |
| US6-AC3 invariants are reportable     | `integration`          | `test_stock.py::test_invariants_are_clean_on_a_healthy_database`, `..._report_a_corrupted_cache_without_a_500`                                                                        |
| US6-AC4 explain a count from the UI   | `e2e`                  | `tests/e2e/`, landing with T4.4                                                                                                                                                       |

Those test names are relative to the suite's own directory. When this table and the code disagree,
the code wins and the table is wrong — fix the table in the same PR.

US2's three claims are owned by `tests/integration/test_concurrency.py`, the live-server contention
suite that lands with T4.3 (#40); that file is not on `main` yet. On this branch only AC3 has a
proof: `test_orders_qa.py::test_ten_concurrent_multiline_orders_leave_no_partial_reservation` runs
ten simultaneous multi-line orders and asserts no partial reservation, no `500` and a clean ledger.
US2-AC1 (twenty orders for the last unit produce exactly one `201`) and US2-AC2 (fifty consecutive
runs, never a `500`) are an open coverage gap until #40 merges.
`test_orders.py::test_concurrent_cancels_release_exactly_once` is not a US2 proof — it is a US3-AC2
test asserting that a concurrent double cancel releases once.

## 4. Writing a unit test

- **Fails first.** State the AC id in a comment or the docstring, then write the assertion that
  would fail if the behaviour were reverted. A unit test that cannot fail is documentation.
- **No I/O.** No `Session`, no `TestClient`, no sockets, no `time.sleep`. `make test-unit` must stay
  fast enough to run on every save.
- **Keep the domain pure.** `tests/unit/test_domain_purity.py` reads `backend/domain/**`'s imports and
  fails if a session or HTTP library appears there. Test that rule, do not relax it.
- **One seam per file.** `test_domain_*.py` tests `backend/domain`; `test_api_*.py` tests the
  validation seams in `backend/api`; `test_openapi_contract*.py` tests the generated document.
- **Do not duplicate.** If a clause is already asserted, cite the node id (`pytest -q
tests/unit/test_domain_orders.py::test_a_cancelled_order_cannot_be_fulfilled`) instead of adding
  a second test that would pass even if the first were deleted.
- **Parametrise the boundaries**, not the middles: zero, one, `reorder_point`, `reorder_point + 1`,
  blank, whitespace-only, and the wrong type (`True` is an `int` subclass — test it).
- **`ruff` checks `tests/`.** Run `make lint` before pushing, not only `pytest`.

## 5. When a claim has no pure seam

Some `unit` claims are implemented inline in a database transaction — US1-AC3's price snapshot is
written inside the reservation transaction in `backend/api/orders.py`. Do not invent a seam to make
the tag work; that is a product change. Instead:

1. Let the integration test own the behaviour end to end.
2. Name the missing `unit` seam in the issue or PR under **Known coverage gaps**, with the test that
   proves the behaviour today.

A gap recorded honestly is cheaper than a seam created to satisfy a label.
