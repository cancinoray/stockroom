# AGENTS.md

Read this first, then only the documents your task needs. The map below is the context — do not
read the whole repository to "get up to speed".

## What this is

**Stockroom** — order and inventory management for a single-warehouse distributor. FastAPI +
PostgreSQL backend, React/Vite frontend, `openapi.yaml` as the contract between them. The product
is a correctness core (atomic reservation, append-only ledger), not a CRUD demo.

Agent setup is tool-neutral: `AGENTS.md` is the only entry point, and `.agents/` holds the role
and skill definitions. Nothing here depends on a specific editor or vendor.

## Commands

| Command | Does |
| --- | --- |
| `make install` | Backend (`uv sync`) and frontend (`npm ci`) dependencies; run once after clone |
| `make dev` | Docker Compose up: app + Postgres, migrate, seed. The single-command path from the README |
| `make run` | Backend only, reload mode, for backend work |
| `make test` | Backend unit + frontend unit tests. Must pass before any PR |
| `make test-unit` | Fast, no database |
| `make test-integration` | httpx against a real Postgres |
| `make e2e` | Playwright against a running stack |
| `make lint` | ruff, ruff format --check, tsc, eslint |
| `make migrate` / `make seed` / `make reset` | Alembic upgrade, idempotent seed, drop and reseed |

Targets arrive with their phases: `make dev` in T1.4, integration and migrations in P2, e2e in P4.
If a target exists but is broken, fix it — do not work around it.

## Rules

1. **The ledger is append-only.** Stock changes by inserting a `movement`. Never `UPDATE` or
   `DELETE` one, not even in a test helper.
2. **Every stock write is one transaction**, locking stock rows in ascending `sku` order, with the
   validation inside the same lock.
3. **`stock.on_hand` and `stock.reserved` are caches.** Movements are the truth. Never hand-fix a
   counter; report drift.
4. **No customer data or secrets in telemetry.** `order_id`, `sku`, `trace_id`, `customer_ref` are
   allowed. Names, emails, tokens, connection strings are not.
5. **The contract moves with the code.** A shape change means `openapi.yaml` + regenerated client
   in the same PR.
6. **Every behaviour change ships a test that fails without it.** No failing test first means the
   task is not understood yet.
7. **Shipped migrations are immutable.** Add a new one.
8. **Agents never merge, deploy to production, rotate secrets, or run SQL against production.**
   Those are human gates.
9. **Stay inside the issue's constraints.** New ideas become issues, not a bigger diff.

## Documents

| Read | When |
| --- | --- |
| [_docs/handoff.md](_docs/handoff.md) | First, if you are picking up work you did not start |
| [_docs/process.md](_docs/process.md) | Always — roles, grooming, the loop, the orchestrator, definition of done |
| [_docs/task-template.md](_docs/task-template.md) | When grooming or filing an issue |
| [product-spec.md](product-spec.md) | Always — your task cites acceptance criteria here |
| [_docs/domain.md](_docs/domain.md) | Any backend, data or test work |
| [_docs/plan.md](_docs/plan.md) | If you need to know why something is out of scope |
| [_docs/backlog.md](_docs/backlog.md) | To find your task before the tracker exists |
| [_docs/team/](_docs/team/) | If you are running as a PM, engineer, QA or on-call agent |
| [_docs/ai-usage-report.md](_docs/ai-usage-report.md) | Append an entry when you finish |

Written later, as the matching phase starts: `_docs/testing-guidelines.md`, `_docs/api.md` (both
P1), `_docs/design-system.md` (P3), `_docs/deployment.md` and `_docs/release-process.md` (P5),
`_docs/runbooks/` (P6).

## Working on a task

1. Find the issue in the tracker and read its acceptance criteria. Ambiguous criteria: stop and
   ask, do not guess.
2. Branch as `<type>/<issue>-<slug>`, e.g. `feat/14-atomic-reservation`.
3. Failing test first, then the smallest change that passes.
4. `make lint && make test`; paste the output into the PR.
5. PR titled `feat: atomic reservation (#14)`, body with `Closes #14`, the AC ids, and the
   commands you ran.
6. Append an entry to `_docs/ai-usage-report.md`.

## Definition of done

- [ ] Every referenced AC has a test that fails if the behaviour is reverted
- [ ] `make lint` and `make test` pass locally
- [ ] `openapi.yaml` and the generated client are current
- [ ] Errors are `application/problem+json` with a `trace_id`
- [ ] No PII or secret in logs, traces, metrics, or committed config
- [ ] PR links the issue and lists the ACs
- [ ] `_docs/ai-usage-report.md` has an entry

## Repo map

```
backend/            FastAPI: api/ (routes), domain/ (rules, no I/O), db/ (models, migrations)
frontend/           React + Vite; api/ (generated client), features/, components/
tests/              unit/, integration/, e2e/
observability/      collector config, dashboards, alert rules
on-call-engineer/   alert poller, evidence collector, responder task, autonomy policy, incidents/
.agents/            skills/ and agents/ definitions (plain Markdown, tool-neutral)
_docs/              process, domain, plan, team roles, runbooks, reports
openapi.yaml        the contract
```
