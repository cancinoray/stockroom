# AGENTS.md

Entry point for coding agents working in this repository. Read this file first, then only the
docs relevant to your task. Do not read the whole repository to "get context" — the map below is
the context.

## What this is

**Stockroom** — order and inventory management for a single-warehouse distributor. FastAPI +
PostgreSQL backend, React/Vite frontend, `openapi.yaml` as the contract between them. The point of
the system is a correctness core (atomic reservation, append-only ledger), not breadth of CRUD.

## Map: read what your task needs

| Topic | Document | When |
| --- | --- | --- |
| Behaviour, stories, acceptance criteria | [product-spec.md](product-spec.md) | Always — your task cites an AC id |
| Schema, ledger semantics, locking | [docs/domain.md](docs/domain.md) | Any backend, data or test work |
| Roles, handoffs, definition of done | [docs/process.md](docs/process.md) | Before opening a PR |
| Phases, schedule, risks | [docs/plan.md](docs/plan.md) | If you need to know why something is out of scope |
| Task list with ACs and estimates | [docs/backlog.md](docs/backlog.md) | To find your task |
| How AI was used and verified | [docs/ai-usage-report.md](docs/ai-usage-report.md) | Append an entry when you finish |

Docs added as phases complete: `docs/architecture.md` (contract + skeletons), `docs/testing.md`
(integration tests), `docs/deployment.md` and `docs/release-process.md` (deploy), `docs/runbooks/`
(observability).

## Command contract

These are the only commands you need. If one is broken, fix it — do not work around it.

| Command | Does |
| --- | --- |
| `make dev` | Compose up app + Postgres, migrate, seed. The single-command path from the README |
| `make test` | Unit + integration + frontend unit tests. Must pass before any PR |
| `make test-unit` | Fast, no database |
| `make test-integration` | httpx against a real Postgres |
| `make e2e` | Playwright against a running stack |
| `make lint` | ruff, ruff format --check, tsc, eslint |
| `make migrate` / `make seed` / `make reset` | Alembic upgrade, idempotent seed, drop and reseed |

Added in T1.1; the contract is fixed even while the targets are being written.

## Non-negotiables

1. **The ledger is append-only.** Stock changes by inserting a `movement`. Never `UPDATE` or
   `DELETE` a movement, not even in a test helper, not even "just this once".
2. **Every stock write is one transaction**, and it locks stock rows in ascending `sku` order.
   Anything that reads stock, validates and then writes must hold the lock across both steps.
3. **`stock.on_hand` and `stock.reserved` are caches.** The sum of movements is the truth. If you
   need a number, derive it when the cache is suspect and report drift — do not "fix" the cache by
   hand.
4. **No customer data or secrets in telemetry.** `order_id`, `sku`, `trace_id`, `customer_ref`
   are allowed. Names, emails, tokens, connection strings are not. No PII in log messages at any
   level.
5. **The contract moves with the code.** A change to an endpoint's request or response shape is a
   change to `openapi.yaml` in the same PR, plus a regenerated frontend client.
6. **Every behaviour change ships a test that fails without it.** If you cannot write the failing
   test first, the task is not understood yet.
7. **Shipped migrations are immutable.** Add a new one.
8. **Agents do not merge, deploy to production, rotate secrets, or run SQL against a production
   database.** Those are human gates (see [docs/process.md](docs/process.md)).

## Working on a task

1. Find the task in the tracker (or [docs/backlog.md](docs/backlog.md)) and read its acceptance
   criteria. If the criteria are ambiguous, stop and ask — do not guess.
2. Create a branch named `<type>/<issue>-<slug>`, e.g. `feat/14-atomic-reservation`.
3. Write the failing test first (unit for domain logic, integration for HTTP + database).
4. Implement the smallest change that passes. Do not refactor unrelated code in the same PR.
5. Run `make lint && make test`. Paste the result in the PR description.
6. Open a PR titled `feat: atomic reservation (#14)` with `Closes #14` in the body, the AC ids it
   satisfies, and the commands you ran.
7. Append an entry to [docs/ai-usage-report.md](docs/ai-usage-report.md): what you changed, what
   you verified, what you chose not to do.

## Definition of done

A task is done when **all** of these are true:

- [ ] Every referenced AC has a test, and that test fails if the behaviour is reverted
- [ ] `make lint` and `make test` pass locally
- [ ] `openapi.yaml` is updated if any shape changed, and the client is regenerated
- [ ] Errors use `application/problem+json` and include `trace_id`
- [ ] No PII or secret appears in logs, traces, metrics, or committed config
- [ ] The PR links its issue and lists the ACs it satisfies
- [ ] `docs/ai-usage-report.md` has an entry

## Repo map

```
backend/            FastAPI app: api/ (routes), domain/ (rules, no I/O), db/ (models, migrations)
frontend/           React + Vite; api/ (generated client), features/, components/
tests/              unit/, integration/, e2e/
observability/      collector config, dashboards, alert rules
incident-response/  evidence collector, responder task, autonomy policy, incident records
docs/               process, domain, plan, runbooks, reports
openapi.yaml        the contract
```
