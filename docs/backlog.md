# Backlog

The task list that becomes GitHub Issues in T0.4. Every task cites the acceptance criteria it
satisfies ([product-spec.md](../product-spec.md)); a task with no AC id is infrastructure and must
say what it unblocks instead.

Status here is a mirror. The tracker is the live source of truth once T0.4 is done.

**Totals:** 26 tasks, ~24.5h core + ~4.5h stretch, plus 3h peer reviews.
Phase totals: P0 3 · P1 4 · P2 5 · P3 3 · P4 2 · P5 2 · P6 2 · P7 2 · P8 1.5

## Conventions

- **Branch:** `<type>/<issue>-<slug>` — `feat/14-atomic-reservation`
- **Labels:** `type:feature|test|ops|docs|chore` · `area:backend|frontend|contract|infra|observability` · `phase:0..8` · `size:S|M|L` · `blocked`
- **Board columns:** `Backlog → Ready → In progress → In review → QA → Done`
- **WIP limit:** one card in progress per agent
- Every issue body carries the AC checklist and the command that proves it

## Phase 0 — Spec and context

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T0.1 | Repo init, `.gitignore`, README with problem statement | — | 0.5 | `chore` `docs` `phase:0` |
| T0.2 | `product-spec.md` v1: 6 stories, 24 ACs, invariants, lifecycle, API surface, non-goals | all | 1 | `docs` `phase:0` |
| T0.3 | `AGENTS.md` router + `docs/domain.md` + `docs/process.md` | — | 0.75 | `docs` `phase:0` |
| T0.4 | Public GitHub repo, labels, Project board, 26 issues mirrored from this file | — | 0.75 | `chore` `phase:0` |

**Exit:** a stranger reads the spec and can state what the app does, how it can fail, and who is
allowed to do what.

## Phase 1 — Contract and walking skeleton

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T1.1 | Backend skeleton: app factory, settings, `/healthz`, `/api/version`, ruff, `Makefile` | — | 1 | `area:backend` `infra` `phase:1` |
| T1.2 | `openapi.yaml` v1 + spectral lint in CI | — | 1 | `area:contract` `phase:1` |
| T1.3 | Frontend skeleton: Vite + TS + Tailwind + TanStack Query + client generated from contract | — | 1 | `area:frontend` `phase:1` |
| T1.4 | CI workflow (lint, unit, build) + Fly `dev` app + deploy the walking skeleton | — | 1 | `infra` `phase:1` |

**Exit:** `make dev` serves a page; a public dev URL answers `/healthz`; CI runs on every PR.

## Phase 2 — Backend core

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T2.1 | Schema + Alembic: products, warehouses, stock, movements, orders, order_lines, checks, append-only trigger | I1, I4 | 0.75 | `area:backend` `phase:2` |
| T2.2 | Idempotent seed: one warehouse, 8 SKUs with reorder points, opening `receive` movements | — | 0.25 | `area:backend` `phase:2` |
| T2.3 | Domain layer: order state machine, movement writer, invariant checker (no HTTP, no ORM session leaks) | US3-AC2, US4-AC2, US4-AC3, I2, I3 | 1.25 | `area:backend` `phase:2` |
| T2.4 | Reservation transaction + `POST /api/orders` (ordered `FOR UPDATE`, all-or-nothing, per-line 409) | US1-AC1..5, US2-AC3, I5, I6 | 1.25 | `area:backend` `phase:2` |
| T2.5 | Stock endpoints: list, receive, adjust, movements; `/api/invariants` | US5-AC1..5, US6-AC2, US6-AC3 | 0.75 | `area:backend` `phase:2` |
| T2.6 | Order endpoints: list, get, cancel, fulfil | US3-AC1, US4-AC1 | 0.5 | `area:backend` `phase:2` |
| T2.7 | `application/problem+json` errors with `trace_id`, request validation | US1-AC5 | 0.25 | `area:backend` `phase:2` |

**Exit:** every backend AC has a passing integration test; `/api/invariants` reports `ok`.

## Phase 3 — Frontend

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T3.1 | Generated typed client, query hooks, error normalization (problem+json → form error) | — | 0.5 | `area:frontend` `phase:3` |
| T3.2 | Inventory screen: table, low badges, receive and adjust dialogs with reason + note | US6-AC1 | 1 | `area:frontend` `phase:3` |
| T3.3 | Place-order screen: SKU search, live availability, per-line 409 rendering | US1-AC1 | 1 | `area:frontend` `phase:3` |
| T3.4 | Orders list, detail drawer, movement timeline | US6-AC4 | 0.5 | `area:frontend` `phase:3` |

**Exit:** the three screens work against the deployed dev API; no hand-written response types.

## Phase 4 — Tests

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T4.1 | Unit suite: price snapshot, quantity validation, state machine, availability math, low-stock, note rules | US1-AC3, US1-AC4, US3-AC2, US4-AC2, US4-AC3, US5-AC4, US6-AC1 | 0.75 | `type:test` `phase:4` |
| T4.2 | Integration suite: fixtures, migrations applied, real Postgres, full AC coverage | US1-AC1, US1-AC2, US1-AC5, US3-AC1, US3-AC3, US4-AC1, US5-AC1..3, US6-AC2, US6-AC3 | 0.5 | `type:test` `phase:4` |
| T4.3 | Concurrency test: barrier + threadpool against live uvicorn, 50 iterations, two-SKU deadlock variant | US2-AC1..3 | 0.5 | `type:test` `phase:4` |
| T4.4 | Playwright: place → fulfil happy path; short-line failure path; vitest for inventory table | US6-AC1, US6-AC4 | 0.25 | `type:test` `phase:4` |

**Exit:** `make test` green from a clean clone; removing the `FOR UPDATE` makes the concurrency
test fail (verified by hand, noted in the PR).

## Phase 5 — Ship

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T5.1 | Multi-stage Dockerfiles, compose with Postgres, healthchecks, migrate-on-start entrypoint | — | 0.75 | `infra` `phase:5` |
| T5.2 | CI: separate integration job, container build with cache | — | 0.5 | `infra` `phase:5` |
| T5.3 | Deploy workflow: dev on merge, prod behind GitHub Environment approval, migrate pre-release, post-deploy smoke test | — | 0.5 | `infra` `phase:5` |
| T5.4 | Rollback rehearsal + `docs/deployment.md` + `docs/release-process.md` | — | 0.25 | `docs` `phase:5` |

**Exit:** clean machine runs `docker compose up --build`; merge deploys dev; approval deploys prod;
a documented rollback returns to the previous release in under two minutes.

## Phase 6 — Observability

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T6.1 | OTel: traces for the order journey, metrics (placed, failed, latency, conflicts, drift gauge), JSON logs with `trace_id`, PII scrub, resource attrs (service, version, env) | — | 0.75 | `area:observability` `phase:6` |
| T6.2 | Grafana Cloud OTLP wiring, dashboard JSON in `observability/`, panel links from dashboard to trace search | — | 0.75 | `area:observability` `phase:6` |
| T6.3 | Three alert rules (error rate, p95 latency, invariant violation) + runbooks | — | 0.5 | `area:observability` `phase:6` |

**Exit:** one trace id appears in the trace, the logs and the metric exemplar for the same request;
each alert has a runbook and has been fired on purpose at least once.

## Phase 7 — On-call agent

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T7.1 | `collect-evidence.sh`: allowlisted read-only queries → `evidence.json` with the alert, the version, the failing trace ids, the recent deploys | — | 0.75 | `type:ops` `phase:7` |
| T7.2 | `responder-task.md`, `autonomy-policy.yaml`, `response.schema.json`, headless runner with a 10-minute budget | — | 0.75 | `type:ops` `phase:7` |
| T7.3 | Fire drill: inject the fallback-plan fault, record the incident, verify recovery, note any escalation | — | 0.5 | `type:ops` `phase:7` |

**Exit:** one recorded incident shows alert → evidence → diagnosis → proposed fix PR → verified
recovery, with the policy decision visible.

## Phase 8 — Docs and demo

| Id | Task | AC | h | Labels |
| --- | --- | --- | --- | --- |
| T8.1 | README final, screenshots, architecture diagram | — | 0.5 | `docs` `phase:8` |
| T8.2 | `docs/ai-usage-report.md` and `docs/operations-and-security-report.md` complete | — | 0.5 | `docs` `phase:8` |
| T8.3 | 3-minute demo video per the script in [docs/plan.md §6](plan.md), submission form | — | 0.5 | `docs` `phase:8` |

## Stretch — only if Phase 5 ends early

| Id | Task | Why | h |
| --- | --- | --- | --- |
| S1 | Idempotent order creation (`Idempotency-Key`) | Best effort-to-value ratio: a distinct failure mode, cheap to test, strong for criterion 5 | 1.5 |
| S2 | Multi-warehouse: path scoping, per-warehouse locks | The schema already allows it; exercises the locking story deeper | 2 |
| S3 | Load-test report (k6 or locust) against the deployed dev app | Turns "it should scale" into a number; feeds the observability story | 1 |

## Issue template

```markdown
## Task
<one paragraph: what and why>

## Acceptance criteria
- [ ] US1-AC1 <criterion text>
- [ ] US1-AC2 <criterion text>

## Out of scope
<what this task deliberately does not do>

## How to prove it
`make test-integration -k reserve` — expected: 3 passed

## Dependencies
#<issue> (blocked until merged)
```
