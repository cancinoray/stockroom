# Operations and Security Report

The reviewer's map to the operational half of Stockroom: the ledger, the reservation transaction,
secrets, the release path, observability, the on-call responder and the limits of what is actually
proven. Each section answers one question and ends with the repository links that make the claim
checkable.

This is a map, not a second copy of the rules. The trigger lives in the migration, the locking in
`backend/api/orders.py`, the thresholds in `observability/alerts.yaml`, and the autonomy policy in
`on-call-engineer/autonomy-policy.yaml`. Where a rule is stated once, this report links to it.

Claims are taken from the merged repository at P7 (through `1ac2212`, the #66 merge) and from the
session entries they name. The numbers that appear below are read from the files or the recorded
run; none are estimated.

## 1. The append-only ledger and how it is enforced

`movements` is the source of truth. `stock.on_hand` and `stock.reserved` are denormalised caches kept
for hot-path reads, and every counter change is accompanied by exactly one movement row in the same
transaction. That is what makes `available = on_hand - reserved` meaningful and drift detectable
rather than invisible (D4 in the [handoff](handoff.md)).

Two mechanisms enforce append-only behaviour:

- **The database.** Migration `0001_schema_constraints` creates a `BEFORE UPDATE OR DELETE` row
  trigger, `movements_append_only`, whose function raises
  `restrict_violation` with `movements are append-only: <operation> is not permitted`. The trigger is
  the part a reader can verify today; it does not depend on the application behaving.
- **The API.** The ledger is read-only over HTTP. `GET /api/stock/{sku}/movements` is the only
  movements route, and the contract declares only `get` for it; `test_movements_expose_no_mutation_endpoint`
  asserts exactly that.

The movement semantics — `receive`, `adjust`, `reserve`, `release`, `ship` and the two counter
deltas each one carries — are defined in [_docs/domain.md](domain.md) §2 and implemented as pure
values in `backend/domain/movements.py`. The transaction that writes them is described in the next
section.

The database also holds the `check (reserved <= on_hand)` constraint on `stock`, so a logic bug
becomes a failed transaction rather than silent corruption. `GET /api/invariants` runs I2/I3 (the
cached counters must equal the ledger for every SKU) and I5 (a confirmed order holds exactly one
reservation per line), and never returns `500`. The `InventoryInvariantViolation` alert fires when
the exported drift gauge is above zero.

The tests that pin the claim:

- `tests/integration/test_schema.py` issues a direct `UPDATE` and a direct `DELETE` against
  `movements` and asserts both raise with `append-only`.
- `tests/integration/test_stock_qa.py::test_a_movement_written_by_the_stock_api_stays_append_only`
  writes a movement through the stock API and then tries to tamper with it.
- `tests/integration/test_stock.py` proves the invariants report is clean on a healthy database and
  reports a corrupted cache without a `500`.

One honest gap: [_docs/domain.md](domain.md) §2 also describes a production application role
granted only `INSERT`/`SELECT` on `movements`, and a dedicated `admin` role for creating corrupt rows
in tests. No migration creates either role or grant. The trigger is therefore the enforced mechanism
in this repository, and the admin-role gap is the same one Sessions 35 and 37 recorded. It is listed
again under [known limitations](#7-known-limitations).

**Repository links:**
[`backend/db/versions/0001_schema_constraints.py`](../backend/db/versions/0001_schema_constraints.py) ·
[`backend/domain/movements.py`](../backend/domain/movements.py) ·
[`backend/domain/invariants.py`](../backend/domain/invariants.py) ·
[`backend/api/stock.py`](../backend/api/stock.py) ·
[`tests/integration/test_schema.py`](../tests/integration/test_schema.py) ·
[`tests/integration/test_stock.py`](../tests/integration/test_stock.py) ·
[`tests/integration/test_stock_qa.py`](../tests/integration/test_stock_qa.py) ·
[`_docs/domain.md`](domain.md) ·
[`observability/alerts.yaml`](../observability/alerts.yaml)

## 2. The all-or-nothing transaction and ordered locking

Every stock write is one transaction. For a new order, `backend/api/orders.py` opens
`session.begin()`, locks every stock row the order touches with `SELECT … WHERE sku = ANY(:skus)
ORDER BY sku FOR UPDATE`, validates every line against the fresh values while holding the locks,
then inserts the order, its lines and one `reserve` movement per line, updates the cached counters,
and commits. If any line is short, the whole transaction rolls back and the response is a per-line
`409 insufficient_stock`; no order, line or movement survives. Cancel and fulfil go through the same
shape in `_transition_order`, which locks the order row and then the stock rows in ascending SKU
order.

The ordering is the point. Two multi-line orders that touch the same SKUs in different line orders
would form a wait-for cycle if locks were taken in request order. Sorting by `sku` first makes every
transaction walk the same sequence, so a deadlock cannot form by construction (D6). The alternative
— a conditional `UPDATE … WHERE on_hand - reserved >= :qty` per line — is atomic per SKU but turns a
multi-line all-or-nothing rule into "update, watch a count, roll back", and is documented as a
fallback rather than the starting point. `check (reserved <= on_hand)` is the database backstop if
the validation itself is wrong.

The live proof is `tests/integration/test_concurrency.py`, not a mocked or in-process test:

- `threading.Barrier(20)` releases twenty requests at the same instant through
  `ThreadPoolExecutor(max_workers=20)` against a live `uvicorn` on an ephemeral port.
  `TestClient` is deliberately not used because it is synchronous and could accidentally serialise
  the requests, which would make the test pass for the wrong reason.
- `ITERATIONS = 50`, so the suite makes 1,000 requests for the last free unit. Each iteration must
  produce exactly one `201` and nineteen `409`, `reserved == 1`, `available == 0`, a clean ledger
  and no `500`.
- `test_opposing_line_order_cannot_deadlock_or_leave_a_half_reserved_order` runs both line orders
  against the same SKU pair, which is the deadlock-prevention claim rather than the reservation
  claim.

Run it with `make test-integration`, or narrowly with
`uv run pytest tests/integration/test_concurrency.py`. `_docs/testing-guidelines.md` §3 records which
suite owns the claim.

**Repository links:**
[`backend/api/orders.py`](../backend/api/orders.py) ·
[`backend/domain/reservation.py`](../backend/domain/reservation.py) ·
[`backend/domain/movements.py`](../backend/domain/movements.py) ·
[`tests/integration/test_concurrency.py`](../tests/integration/test_concurrency.py) ·
[`_docs/domain.md`](domain.md) ·
[`_docs/testing-guidelines.md`](testing-guidelines.md)

## 3. Secrets and personally identifiable information

**The rule.** [AGENTS.md](../AGENTS.md) rule 4: no customer data or secrets in telemetry. The
allowed identifiers are `order_id`, `sku`, `trace_id` and `customer_ref`; names, emails, tokens and
connection strings are not. The invariant report follows the same rule: it reports a rule id, a SKU
and the two disagreeing numbers, nothing that identifies a customer.

**The telemetry scrub.** `backend/telemetry.py` is the single owner of traces, metrics and logs:

- Resource attributes are only `service.name`, `service.version` and `deployment.environment`; the
  collector turns them into the Prometheus labels the alert rules template on.
- Request-derived span attributes are an allowlist: the route template, method, status,
  `duration_ms`, and the SQL statement's `db.system`, `db.operation` and error class. The statement
  text and its parameters never reach a span.
- `http.target`, `http.url`, `url.full` and `url.query` (plus user agent and peer address) are
  overwritten with `redacted` before export.
- The app's own request log carries the route template, method, status and duration. The rebuilt
  `uvicorn.access` line keeps only the path and discards everything from the first `?` — that strip
  is what stops an API key or a DSN in a query string from reaching Loki, and it was the T6.1 QA
  fix recorded in Session 35.
- An export failure is rate-limited, redacted and never prints headers, the endpoint token or the
  exception text. Turning the exporter off is a supported state: unset `OTEL_EXPORTER_OTLP_ENDPOINT`
  means the app still traces, logs and counts locally and exports nothing.

**Configuration.** `backend/config.py` reads the DSN from `STOCKROOM_DATABASE_URL` and the OTLP
settings from the standard `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_HEADERS` names. The
DSN in `compose.yaml` (`stockroom:stockroom@db:5432/stockroom`) is a throwaway local-development
value on the Compose network, not a production secret. `.env` and `.env.*` are ignored; only
`.env.example` is committed, and it carries no credential. `*.pem` is ignored. A `git grep` for
common token and private-key headers over the tracked tree returns nothing (audit run,
2026-11-08).

**CI.** The workflow declares `contents: read` at the top. Only the `release` job adds
`packages: write`, and it logs in to GHCR with `github.token`; there is no deployment secret in the
workflow. Deployment credentials stay on the host, and the release process documents the scoped
`read:packages` fallback rather than a committed token.

**On-call.** The responder gets no production credentials. `autonomy-policy.yaml` denies
`secret.read`, `secret.print`, `secret.rotate`, `deploy`, `ssh` and `sql.execute`, among others. The
runner builds an allowlisted child environment; git authenticates through a `GIT_ASKPASS` helper
that reads `GH_TOKEN` at run time, so no credential is written to disk; and the AC4 test scans the
isolated HOME, the response, stdout/stderr and the worktree for a sentinel.

**Tests that cover it:** the telemetry unit, integration and QA suites; the alert/runbook scan for
PII and secrets; the observability stack scan; and the evidence-packet denylist.

**Repository links:**
[`AGENTS.md`](../AGENTS.md) ·
[`backend/telemetry.py`](../backend/telemetry.py) ·
[`backend/config.py`](../backend/config.py) ·
[`compose.yaml`](../compose.yaml) ·
[`.env.example`](../.env.example) ·
[`.gitignore`](../.gitignore) ·
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) ·
[`on-call-engineer/autonomy-policy.yaml`](../on-call-engineer/autonomy-policy.yaml) ·
[`on-call-engineer/run_responder.py`](../on-call-engineer/run_responder.py) ·
[`tests/unit/test_telemetry.py`](../tests/unit/test_telemetry.py) ·
[`tests/integration/test_telemetry_qa.py`](../tests/integration/test_telemetry_qa.py) ·
[`tests/unit/test_alerts.py`](../tests/unit/test_alerts.py) ·
[`tests/unit/test_oncall_evidence.py`](../tests/unit/test_oncall_evidence.py) ·
[`tests/integration/test_responder_run.py`](../tests/integration/test_responder_run.py)

## 4. CI/CD and the release path

**CI.** `.github/workflows/ci.yml` has four jobs:

- `test` — `make install`, `make lint`, `make test` (unit + frontend), the generated-contract check
  (`npm run check:contract`) and a Spectral lint of `openapi.yaml`.
- `integration` — `make test-integration` against a real `postgres:16` that the suite starts itself.
- `docker-build` — pull requests only; it builds the image to warm the BuildKit cache and never
  publishes.
- `release` — a push to `main` or a manual dispatch, after `test` and `integration` pass. It
  computes one `YYYYMMDD-HHMMSS-<7-hex-sha>` tag, rejects an existing tag (a release tag is never
  overwritten), builds once, logs in to GHCR with `github.token`, pushes, and writes the image id
  and pushed digest to the job summary. The job-level permission is `packages: write`; nothing else
  gets it.

There is no deploy step and no deploy credential in CI. CI stops at the pushed tag.

**The human release.** The host runs the same `compose.yaml` with a different image reference. The
procedure in [_docs/release-process.md](release-process.md) §3 is: pull the new tag, run
`alembic upgrade head` in a one-off container while the previous release still serves, swap with
`docker compose up -d`, wait for `(healthy)`, and run `scripts/release-smoke.sh`. The smoke script
checks `GET /healthz` (`status` and `db`), `GET /` (200, `text/html`, the built app root) and
`GET /api/version`, and exits non-zero on any failure.

**Rollback.** One command returns the stack to the previous tag:
`STOCKROOM_IMAGE=<previous-tag> docker compose up -d`, followed by `docker compose ps`,
`docker inspect` and the same smoke. The engineer rehearsal measured **17.591 s** from invoking the
rollback to the smoke exiting 0, against a 120 s budget, with the previous tag already in the image
store (Session 30); a human rehearsal is recorded on issue #12. Rolling back across a release that
shipped a migration is explicitly **not** covered: migrations are forward-only, and an older image
meets an `alembic_version` it does not know and exits at startup.

**Release identity.** `/api/version` answers `commit` and `build_time` as `unknown` because neither
`compose.yaml` nor the `Dockerfile` sets `STOCKROOM_COMMIT` / `STOCKROOM_BUILD_TIME`. The release is
identified by the image reference in `docker compose ps` or by `docker inspect`, not by the endpoint.
That limitation is also in §7.

**Repository links:**
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) ·
[`scripts/release-smoke.sh`](../scripts/release-smoke.sh) ·
[`compose.yaml`](../compose.yaml) ·
[`Dockerfile`](../Dockerfile) ·
[`_docs/deployment.md`](deployment.md) ·
[`_docs/release-process.md`](release-process.md)

## 5. Observability and alerts

**One trace id across three signals.** `backend/telemetry.py` installs a `TracerProvider` and
`MeterProvider` (never process-globally, so a test can inject in-memory collectors), a resource
shared by spans, logs and metrics, one child span per SQL statement through SQLAlchemy engine
events, a pure-ASGI request middleware, a JSON log formatter and context filter, and a drift monitor
and gauge. The trace id in the JSON logs, the metric exemplar and the `problem+json` body is the
active span's 32-hex id, not a separately minted one. The five metrics and their bounded labels are
defined there; the collector's `resource_to_telemetry_conversion` turns the resource attributes into
the `service_name`, `service_version` and `deployment_environment` labels that the alert rules use.

**The local stack.** `make observability` starts `app` and `db` plus an OpenTelemetry collector,
Prometheus, Loki, Tempo, Alloy and Grafana, using `compose.observability.yaml`. The app exports OTLP/
HTTP to the collector; the collector forwards traces to Tempo and exposes metrics on `:8889` for
Prometheus; Alloy tails the app's JSON stdout through a read-only Docker socket and pushes it to
Loki; Grafana is provisioned from files. Every observability image is pinned by tag **and** digest,
and there is no `latest`. `make observability-down` stops the stack and keeps the volumes. The
Docker socket mount is local-only and is never part of a deployment.

**The dashboard.** `observability/dashboards/order-journey.json`, uid `stockroom-order-journey`,
provisions five panels — orders placed, orders failed by reason, p95 request latency, reservation
conflicts and invariant drift — and the request panels link to the Grafana trace search for the
trace id in the data.

**The three alerts.** `observability/alerts.yaml` defines exactly one group with three rules:

| Alert                          | Signal                                             | Threshold            | Severity |
| ------------------------------ | -------------------------------------------------- | -------------------- | -------- |
| `StockroomOrderErrorRateHigh`  | order-route 5xx / all order-route requests over 5m | `> 0.05` for 1m      | critical |
| `StockroomOrderLatencyP95High` | p95 order-route duration over 5m                   | `> 2` seconds for 1m | warning  |
| `InventoryInvariantViolation`  | exported drift gauge                               | `> 0` for 1m         | critical |

Each rule carries `service`, `environment` and `version` templated from the metric labels, the
`stockroom-on-call` owner placeholder, and the local dashboard URL. `make check-alerts` runs
`promtool check rules` on the pinned Prometheus image. One runbook per alert lives in
`_docs/runbooks/`, with the exact query, the impact, three read-only checks, the recovery signal and
the autonomy boundary; the recorded firings and their observed values are in those runbooks rather
than duplicated here.

**Deliberately absent.** There is no Alertmanager, routing, silence management, paging integration or
Grafana Cloud stack. Prometheus evaluates the rules on the local stack; delivery is out of scope.

**Repository links:**
[`backend/telemetry.py`](../backend/telemetry.py) ·
[`compose.observability.yaml`](../compose.observability.yaml) ·
[`observability/README.md`](../observability/README.md) ·
[`observability/alerts.yaml`](../observability/alerts.yaml) ·
[`observability/dashboards/order-journey.json`](../observability/dashboards/order-journey.json) ·
[`Makefile`](../Makefile) ·
[`_docs/runbooks/stockroom-order-error-rate-high.md`](runbooks/stockroom-order-error-rate-high.md) ·
[`_docs/runbooks/stockroom-order-latency-p95-high.md`](runbooks/stockroom-order-latency-p95-high.md) ·
[`_docs/runbooks/stockroom-inventory-invariant-violation.md`](runbooks/stockroom-inventory-invariant-violation.md) ·
[`tests/unit/test_observability_stack.py`](../tests/unit/test_observability_stack.py) ·
[`tests/unit/test_alerts.py`](../tests/unit/test_alerts.py)

## 6. On-call: poller, evidence packet and autonomy policy

**The poller.** `make oncall-poll` runs `on-call-engineer/poll_alerts.py` in the foreground;
`ARGS=--once` makes a single pass. (The literal `make oncall-poll --once` is rejected by GNU make as
its own option and exits 2; `make oncall-poll ARGS=--once` is the working form.) The poller reads
Prometheus and Loki on loopback, derives an incident identity from the alert labels plus first-seen
time, and writes at most one frozen-contract packet per firing episode under
`on-call-engineer/evidence/`. `packet.py` owns the allowlists, canonical labels, incident id and
canonical JSON; `state.py` uses `flock` and an atomic temp-file + rename; `collect_evidence.py` runs
the keyed PromQL set, one fixed Loki selector and three app GETs.

**The packet.** It has exactly the frozen top-level and nested key set, no customer data or secret
(a denylist test), and deterministic output: the same inputs and clock produce byte-identical JSON.
Trace ids prefer samples from the order route, so the packet points at the journey the alert is
about rather than at a health check. The real packet and the fixture records are committed in the
repository.

**The autonomy policy.** `on-call-engineer/autonomy-policy.yaml` is versioned. It sets
`default: escalate`, states the precedence — an explicit deny beats everything, escalate beats
allow, allow applies only when neither matched — and defines a `600`-second budget with
`on_exceed: escalate`. It lists the eight binaries the runner shims (`git`, `gh`, `make`, `docker`,
`curl`, `python3`, `uv`, `sh`) and 34 named rules (the `rules:` list in the file). Among the denies: deploy, image push, SSH, any
remote network, secret read/print/rotate, SQL execution, merge, force-push, pushing `main` or
`master`, changing a remote, deleting a branch the responder did not create, and editing protected
paths (`product-spec.md`, `openapi.yaml`, migrations, CI, Compose, the Dockerfile and
`observability/*`). `policy.py` is a pure `decide(action, context, policy)` evaluator with no clock,
environment or file access; every decision names the rule that produced it, and a context field the
rule names but the caller omits does not match, so forgetting a value escalates.

**The runner.** `run_responder.py` (behind `run-responder.sh`) validates the packet, refuses a null
base, creates an isolated worktree at the packet's commit, enforces the budget with a process-group
timeout, builds an allowlisted child environment with an isolated HOME and per-tool shims, validates
the response against the closed `response.schema.json`, and renders the Markdown record from the
validated object. The JSON is the record; the Markdown is a rendering.

**Recovery.** `verify-recovery.sh` reads the recorded alert and rule, checks Prometheus,
`/healthz` and `/api/invariants`, prints one JSON report, and exits 0 only when every check passes.
The P7 drill used it as the recovery authority, not a green log line.

**Incident records.** `on-call-engineer/incidents/` holds the two T7.2 fixture records (explicitly
fixture runs, not diagnoses) and the real T7.3 drill record. The drill reproduced a
fulfil-last-units `500`, wrote one packet, ran the responder to a fix PR against the drill branch
(PR #67, never `main`), and recorded verified recovery. The deterministic drill responder is a
recorded limitation: no model credential reaches the runner's child, and the `claude` CLI could not
authenticate under the isolated HOME. The human sign-off is recorded in `drill-log.md`; the AC6
cleanup fields remain `<unfilled>` (see §7).

**Repository links:**
[`on-call-engineer/poll_alerts.py`](../on-call-engineer/poll_alerts.py) ·
[`on-call-engineer/collect_evidence.py`](../on-call-engineer/collect_evidence.py) ·
[`on-call-engineer/packet.py`](../on-call-engineer/packet.py) ·
[`on-call-engineer/state.py`](../on-call-engineer/state.py) ·
[`on-call-engineer/autonomy-policy.yaml`](../on-call-engineer/autonomy-policy.yaml) ·
[`on-call-engineer/policy.py`](../on-call-engineer/policy.py) ·
[`on-call-engineer/response.schema.json`](../on-call-engineer/response.schema.json) ·
[`on-call-engineer/run_responder.py`](../on-call-engineer/run_responder.py) ·
[`on-call-engineer/verify-recovery.sh`](../on-call-engineer/verify-recovery.sh) ·
[`on-call-engineer/incidents/`](../on-call-engineer/incidents/) ·
[`on-call-engineer/evidence/`](../on-call-engineer/evidence/) ·
[`on-call-engineer/drills/fulfil-last-units-500/drill-log.md`](../on-call-engineer/drills/fulfil-last-units-500/drill-log.md) ·
[`.agents/skills/investigate-alert/SKILL.md`](../.agents/skills/investigate-alert/SKILL.md)

## 7. Known limitations

Each limitation is stated with its mitigation or its accepted risk. This is the uncomfortable
section, and it is deliberately not smoothed over.

- **No authentication (D13).** Every endpoint is open. The deployment is a local/self-hosted demo
  with seeded, non-sensitive data, and authentication is not scored; the accepted risk is that the
  stack must not be put on a public address without a proxy or a clear demo boundary.
  [product-spec.md](../product-spec.md) §8 records the non-goal; [handoff](handoff.md) D13 records
  the decision.
- **Single warehouse.** The schema keeps `warehouse_id`, but only the `MAIN` row is seeded and the
  API exposes one location. Multi-warehouse is a schema-shaped future change, not a v1 feature.
- **Self-hosted Docker Compose, not a managed platform (D2).** Capacity, backups, DNS/TLS and
  restore belong to the host. The restore rehearsal (plan R3) has not been done; the deployment doc
  says so rather than implying a backup exists.
- **O3 — the host has never run a published tag.** Every release, rollback, observability and drill
  rehearsal so far ran on a local Compose stack. `/api/version` still reports `commit` and
  `build_time` as `unknown` because the Compose file and image do not set them. Mitigation: the
  image reference identifies the release, the deployment is a documented human step, and the smoke
  script is the post-start check. Until O3 closes, the deployment rubric is demonstrated locally
  only.
- **O4 is superseded.** No Grafana Cloud stack, OTLP token or retention policy was created. T6.2
  replaced it with the local `make observability` stack. The consequence is accepted: telemetry
  lives in local Docker volumes, is not durable, and there is no hosted dashboard URL to link from
  the README or the video. The plan's R2 fallback became the primary path.
- **Drill evidence is incomplete in one place.** The human sign-off is recorded in
  [drill-log.md](../on-call-engineer/drills/fulfil-last-units-500/drill-log.md) on 2026-11-07, but
  the AC6 cleanup fields remain `<unfilled>`: PR #67 closed (it is evidence, not a merge), the
  `drill/p7-fulfil-last-units-500` and `oncall/...` branches deleted, and the post-merge QA check.
  The drill `README.md` header still says it awaits the human sign-off even though the log records
  it; that is a docs mismatch outside this issue's write scope and a follow-up. The responder's own
  `review.status` is `pending` by design — it cannot sign off its own work.
- **Documentation ahead of code.** [_docs/domain.md](domain.md) §2 describes an `admin` role for
  corrupting a cache row and table-only `INSERT`/`SELECT` grants. No migration creates either role
  or grant. The trigger is the enforced append-only mechanism; the drift drill used the local owner
  through `psql` in a disposable stack, labelled as test corruption, and added no mutation endpoint.
- **Alerts have no delivery.** Prometheus evaluates the three rules, but there is no Alertmanager,
  routing, silence or paging integration. `owner: stockroom-on-call` is a placeholder a human must
  replace in `observability/alerts.yaml` and all three runbooks.
- **The two agent skills are prose, not tested code.** `add-migration` and `investigate-alert` are
  written procedures; nothing executes them. `investigate-alert`'s step 7 names
  `verify-recovery.sh`, which the P7 drill ran, but the skill itself is not part of a test.
- **The session log has one historical hole.** Row 3 (T0.4 tracker setup) is `_pending_` and has no
  detailed entry. This audit did not invent one, and it did not rewrite earlier entries whose
  claims cannot be re-executed; it links to them instead.

**Repository links:**
[`product-spec.md`](../product-spec.md) ·
[`_docs/domain.md`](domain.md) ·
[`_docs/deployment.md`](deployment.md) ·
[`_docs/release-process.md`](release-process.md) ·
[`_docs/plan.md`](plan.md) ·
[`observability/README.md`](../observability/README.md) ·
[`on-call-engineer/drills/fulfil-last-units-500/drill-log.md`](../on-call-engineer/drills/fulfil-last-units-500/drill-log.md) ·
[`on-call-engineer/incidents/`](../on-call-engineer/incidents/) ·
[`_docs/handoff.md`](handoff.md) ·
[`_docs/ai-usage-report.md`](ai-usage-report.md)
