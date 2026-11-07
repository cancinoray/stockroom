# Drill log — `fulfil-last-units-500`

Executed on 2026-11-07 against the local Compose project only. Every value below is copied from a
command's output or an artifact in this repository; nothing is reconstructed. The human sign-off
block is the only part still empty, by design: the responder cannot sign off its own work and this
session is not a human reviewer.

| Field         | Value                                                                                                         |
| ------------- | ------------------------------------------------------------------------------------------------------------- |
| Drill id      | `fulfil-last-units-500`                                                                                       |
| Issue         | #63 (T7.3)                                                                                                    |
| Recorded base | `5f957b5196ab489a687ec1179f5f3c3ce57ce9af` (`origin/main`)                                                    |
| Bug branch    | `drill/p7-fulfil-last-units-500` @ `586031574acaf8d5e74d8b5de313bb464d5d43de`                                 |
| Fix branch    | `oncall/stockroom-order-error-rate-high-a697e0be6f0f-1794071189` @ `0dbf4080782c5c043b3f7e0fdfdba2fff8bc3340` |
| Fix PR        | <https://github.com/cancinoray/stockroom/pull/67> (base `drill/p7-fulfil-last-units-500`, open, not merged)   |
| Incident      | `stockroom-order-error-rate-high-a697e0be6f0f-1794071189`                                                     |
| Status        | `recovery verified`; awaiting human sign-off and the docs/ops PR (AC6)                                        |

## AC1 — approval and injection

- Approver (human): `cancinoray` (owner)
- Approved at (UTC): `2026-11-07T16:58:44Z`
- Approval comment URL (issue #63): <https://github.com/cancinoray/stockroom/issues/63#issuecomment-6710288196>
- `bug.patch` sha256: `5ad186793fe5177cb4e5a5ba817d33a433c026fb925d89d2bce96eccba7ebcfd`
- `git apply --check` output at injection time:

  ```text
  $ git apply --check -v on-call-engineer/drills/fulfil-last-units-500/bug.patch
  Checking patch backend/api/orders.py...
  ```

- Drill branch tip at injection: `586031574acaf8d5e74d8b5de313bb464d5d43de`
- `git diff --stat` on the drill branch:

  ```text
   backend/api/orders.py | 15 ++++++++++++---
   1 file changed, 12 insertions(+), 3 deletions(-)
  ```

- `make test` — passed: `291 passed, 11 warnings in 1.82s` (unit) and
  `Test Files 10 passed (10) / Tests 91 passed | 1 skipped (92)` (frontend).
- `make test-integration` — passed: `208 passed, 15 warnings in 116.40s (0:01:56)`.
- Test files changed: none. The only file the patch touches is `backend/api/orders.py`.

## Environment

`compose.override.yaml` is untracked, machine-local and never committed. It carries the build
identity the image does not set (`_docs/deployment.md` §4), the app port this machine uses, and a
loopback-only database port so the documented `make reset` sequence can reach the local seeded
database. Two versions were used, one per build:

```yaml
# buggy build (drill/p7-fulfil-last-units-500)
services:
  app:
    environment:
      STOCKROOM_COMMIT: "586031574acaf8d5e74d8b5de313bb464d5d43de"
      STOCKROOM_BUILD_TIME: "2026-11-07T17:03:32Z"
    ports: !override
      - "18000:8000"
  db:
    ports:
      - "127.0.0.1:5432:5432"
```

```yaml
# fixed build (oncall/stockroom-order-error-rate-high-a697e0be6f0f-1794071189)
services:
  app:
    environment:
      STOCKROOM_COMMIT: "0dbf4080782c5c043b3f7e0fdfdba2fff8bc3340"
      STOCKROOM_BUILD_TIME: "2026-11-07T17:11:37Z"
    ports: !override
      - "18000:8000"
  db:
    ports:
      - "127.0.0.1:5432:5432"
```

- `/api/version` on the buggy build: `{"version":"0.1.0","commit":"586031574acaf8d5e74d8b5de313bb464d5d43de","build_time":"2026-11-07T17:03:32Z","environment":"development"}`
- App published on `18000` (the documented local deviation; `8000` stays free). Prometheus `9090`,
  Loki `3100`, Tempo `3200`, Grafana `3000`.
- Stack command: `make observability` (builds `stockroom-app:local` from the current checkout).
- `make reset` — exit 0 at `2026-11-07T17:04Z`, run from the host with
  `STOCKROOM_DATABASE_URL=<the throwaway local DSN in compose.yaml, host 127.0.0.1:5432>`, output
  ends `seed: warehouse MAIN, 8 products, 8 new opening movements`. Only the local Compose database
  was touched; no shared or production database.

## AC2 — alert and exactly one packet

- Alert name: `StockroomOrderErrorRateHigh`
- Rule threshold and window as read from the packet: `> 0.05` ratio of 5xx over `5m`, `for: 60s`
- `activeAt` (when it became pending): `2026-11-07T17:05:20.285562485Z`
- First observed `pending`: `2026-11-07T17:05:43Z`, value `0.4444`
- First observed `firing`: `2026-11-07T17:06:23Z`, value `0.4444`
- Prometheus `/api/v1/alerts` exposes `activeAt` and `state`, not a separate `pendingAt`; the two
  observation timestamps above are from the polling loop that watched the endpoint.
- `GET /api/v1/alerts` at firing:

  ```json
  {
    "status": "success",
    "data": {
      "alerts": [
        {
          "activeAt": "2026-11-07T17:05:20.285562485Z",
          "annotations": {
            "description": "44.44% of order-journey requests (POST /api/orders, cancel and fulfil) returned a problem+json 5xx over the last 5m. The threshold is 5%, evaluated for 1m. 4xx responses are excluded. Start at the runbook: _docs/runbooks/stockroom-order-error-rate-high.md",
            "summary": "Order journey is returning 5xx above 5%"
          },
          "labels": {
            "alertname": "StockroomOrderErrorRateHigh",
            "dashboard_url": "http://localhost:3000/d/stockroom-order-journey",
            "deployment_environment": "development",
            "environment": "development",
            "owner": "stockroom-on-call",
            "service": "stockroom",
            "service_version": "586031574acaf8d5e74d8b5de313bb464d5d43de",
            "severity": "critical",
            "version": "586031574acaf8d5e74d8b5de313bb464d5d43de"
          },
          "state": "firing",
          "value": "4.444444444444444e-01"
        }
      ]
    }
  }
  ```

- Traffic: `STOCKROOM_APP_URL=http://localhost:18000 sh drive-traffic.sh` — 3 cycles, 54
  order-journey requests, **24 × 5xx**. Every fulfil of an order that took all remaining available
  units returned 500; every cancel returned 200.
- Poller command, with its env:

  ```text
  ONCALL_BASE_REF=drill/p7-fulfil-last-units-500 \
  ONCALL_BASE_COMMIT=586031574acaf8d5e74d8b5de313bb464d5d43de \
  STOCKROOM_APP_URL=http://localhost:18000 \
    make oncall-poll ARGS=--once
  ```

- Poller output: `{"event": "packet_written", "incident_id": "stockroom-order-error-rate-high-a697e0be6f0f-1794071189", "packet": "stockroom-order-error-rate-high-a697e0be6f0f-1794071189.json"}`
- Evidence packet path: `on-call-engineer/evidence/stockroom-order-error-rate-high-a697e0be6f0f-1794071189.json`
- Incident id: `stockroom-order-error-rate-high-a697e0be6f0f-1794071189`
- Packet sha256: `bfdabd8dc6916438fa2b4a8cf0288b37d8f2ce62d3ec3f0bbb94ae2f232a40ad`
- Packet `repo.base_ref` / `repo.base_commit`: `drill/p7-fulfil-last-units-500` /
  `586031574acaf8d5e74d8b5de313bb464d5d43de` (`source: operator`)
- Packet `service`: name `stockroom`, environment `development`, deployed version
  `586031574acaf8d5e74d8b5de313bb464d5d43de`, owner `stockroom-on-call`, dashboard
  `http://localhost:3000/d/stockroom-order-journey`, runbook
  `_docs/runbooks/stockroom-order-error-rate-high.md`
- Packet log samples: 20 lines, selector `{container=~"stockroom-app.*"} | json | status_code >= 500`
- Packet trace ids: `091d013fa54793eb99b9f4fe6da8d367`, `973b1f80abd0e22a818eb32b0a9b588c`,
  `c8c86aa789ebcf1c766c2c56cce15ae0`
- Opened in Tempo: `GET http://localhost:3200/api/traces/091d013fa54793eb99b9f4fe6da8d367` → 200,
  7 spans: `db.query SELECT`, `db.query SELECT`, `db.query SELECT`, `db.query INSERT`,
  `db.query UPDATE`, `db.query UPDATE`, `POST /api/orders/{id}/fulfil` (Grafana trace search:
  `http://localhost:3000/explore?left=...queryType:%22traceId%22,query:%22091d013fa54793eb99b9f4fe6da8d367%22...`)
- Packets written by the run: exactly one. A second `make oncall-poll ARGS=--once` wrote none and
  left `on-call-engineer/evidence/` at one file.

## AC3 — responder (≤ 600s)

Command (the runner gets `RESPONDER_CMD` as a JSON argv array; `GH_TOKEN` comes from the operator's
`gh` CLI and is never printed, written or committed):

```text
RESPONDER_CMD='["python3","/tmp/drill/responder-drill.py"]' \
STOCKROOM_APP_URL=http://localhost:18000 ONCALL_BUDGET_SECONDS=600 \
  make oncall-respond INCIDENT=stockroom-order-error-rate-high-a697e0be6f0f-1794071189
```

Responder used: **deterministic drill responder**, committed at
`on-call-engineer/drills/fulfil-last-units-500/responder-drill.py` (committed sha256
`b2f682f92ab783205148162920d03d98959af3b85cf2fc0ec1a7fc6a7426c72f`). It runs through the real runner,
policy evaluator, shims, isolated HOME, worktree and schema validation. Limitation: it is a fixed
procedure, not a model.

The copy the run executed is byte-identical in every behavioural line; the committed file differs
only by `ruff format` re-wrapping, the removal of one unused local (`app`), and explicit
`from None` on the two `SystemExit` raises that ruff's B904 requires. Executed copy sha256
`c28b46f09655732c817340a9e4efab5ecf2ff2e55ca161e2080b9c8b4750304e`; both digests are recorded here
so the difference is auditable rather than silent. The `claude` CLI is installed but cannot authenticate under the
runner's isolated HOME — probed directly with an isolated `HOME` and a stripped environment,
result: `returncode 1`, `Not logged in · Please run /login`; the runner also passes no model
credential to the child. No model ran and none is claimed.

Two earlier attempts were recorded by the runner as escalations, both caused by this drill script
rather than the product, and both were fixed before the third run:

1. `fix_did_not_pass` after 3.743s: the regression test asserted movement order `["reserve","ship"]`
   but the contract returns newest first (`["ship","reserve"]`). The fulfilment itself was already
   `200`; the runner still refused to claim a fix. Fixed by comparing sorted reasons.
2. `git_failed` after 3.281s: the commit message's body was passed as three argv items, so git read
   two of them as pathspecs. Fixed by joining the body into one argument.

Final run:

- Worktree: `worktrees/oncall-stockroom-order-error-rate-high-a697e0be6f0f-1794071189` (created by
  the runner at the packet's commit, branch `oncall/<incident-id>`)
- `timing.elapsed_seconds` / `timing.budget_seconds`: **8.727 / 600**
- Reproduced against the running buggy build (`responder-reproduction.json`):
  `POST /api/orders` for all 3 available `SKU-8820` → `201`; `POST /api/orders/<id>/fulfil` →
  **`500`**, problem `type=unexpected`; `POST /api/orders/<id>/cancel` → `200`;
  `GET /api/invariants` → `{"ok": true, "violations": []}` (no drift: the failed transaction rolled
  back).
- Regression test: `tests/integration/test_fulfil_last_units_drill.py`
- Failing run against the buggy base — command and output:

  ```text
  $ /Users/raymondcancino/Desktop/project/stockroom/worktrees/issue-63-bug-drill/.venv/bin/python \
      -m pytest tests/integration/test_fulfil_last_units_drill.py -q
  F                                                                        [100%]
  ...
  >       assert fulfilled.status_code == 200, fulfilled.text
  E       AssertionError: {"type":"unexpected","title":"Unexpected error","status":500,"detail":"An unexpected error occurred.","trace_id":"3072b593dc167aef2571698254881e29"}
  ...
  FAILED tests/integration/test_fulfil_last_units_drill.py::test_a_fulfil_that_takes_every_free_unit_succeeds
  exit 1
  ```

- Passing run with the fix — command and output:

  ```text
  $ /Users/raymondcancino/Desktop/project/stockroom/worktrees/issue-63-bug-drill/.venv/bin/python \
      -m pytest tests/integration/test_fulfil_last_units_drill.py -q
  .                                                                        [100%]
  (warnings only)
  exit 0
  ```

- Fix PR: <https://github.com/cancinoray/stockroom/pull/67>, base `drill/p7-fulfil-last-units-500`,
  head `oncall/stockroom-order-error-rate-high-a697e0be6f0f-1794071189`, open and not merged.
- Incident record: `on-call-engineer/incidents/stockroom-order-error-rate-high-a697e0be6f0f-1794071189.json`
  (schema-validated by the runner and again when the verification block was added) and the rendered
  `.md` from the same object.
- `policy.decisions` — every consequential action, in order, each produced by the policy CLI:

  | #   | action                           | decision | rule_id               |
  | --- | -------------------------------- | -------- | --------------------- |
  | 1   | `read.packet`                    | allow    | `read-packet`         |
  | 2   | `read.repo`                      | allow    | `read-repo`           |
  | 3   | `read.local_endpoint`            | allow    | `read-local-endpoint` |
  | 4   | `git.worktree.create`            | allow    | `worktree-create`     |
  | 5   | `git.branch.create`              | allow    | `branch-create`       |
  | 6   | `run.tests`                      | allow    | `run-tests`           |
  | 7   | `edit` (regression test)         | allow    | `edit-allowed`        |
  | 8   | `edit` (`backend/api/orders.py`) | allow    | `edit-allowed`        |
  | 9   | `git.commit`                     | allow    | `commit`              |
  | 10  | `git.push`                       | allow    | `push-feature`        |
  | 11  | `pr.create`                      | allow    | `pr-create`           |

- Any action taken outside the policy: none. Protected paths were never touched; there was no deny or
  escalate on the successful run.
- Responder's own `review.status`: `pending` (it cannot sign off its own work).

## AC4 — verified recovery

- Buggy stack stopped: `make observability-down`, `2026-11-07T17:11Z`.
- Fixed branch built and started with the same Compose project at
  `2026-11-07T17:11:37Z` (detached at `0dbf4080782c5c043b3f7e0fdfdba2fff8bc3340`; `/api/version`
  reports that commit).
- `verify-recovery.sh` **before** the fix, on the buggy build — output and exit code:

  ```json
  {"alert": "StockroomOrderErrorRateHigh", "checks": [{"detail": "1 StockroomOrderErrorRateHigh alert(s) listed", "name": "alert_absent", "ok": false}, {"detail": "1 series at or above the threshold", "name": "impact_below_threshold", "ok": false}, {"detail": "status=ok db=ok", "name": "app_healthz", "ok": true}, {"detail": "ok=True violations=0", "name": "app_invariants", "ok": true}], "incident_id": "stockroom-order-error-rate-high-a697e0be6f0f-1794071189", "observed_at": "2026-11-07T17:11:16Z", "recovered": false, ...}
  ```

  `make oncall-verify` exit 2 (the script exits 1; make reports the failure).

- Wait: the rule's 5m window held the earlier failures until `2026-11-07T17:15:49Z`, when the alert
  became absent (polled every 10s; it was still firing at `2026-11-07T17:12:09Z`).
- `verify-recovery.sh` **after** the fix — output and exit code:

  ```json
  {"alert": "StockroomOrderErrorRateHigh", "checks": [{"detail": "0 StockroomOrderErrorRateHigh alert(s) listed", "name": "alert_absent", "ok": true}, {"detail": "0 series at or above the threshold", "name": "impact_below_threshold", "ok": true}, {"detail": "status=ok db=ok", "name": "app_healthz", "ok": true}, {"detail": "ok=True violations=0", "name": "app_invariants", "ok": true}], "incident_id": "stockroom-order-error-rate-high-a697e0be6f0f-1794071189", "observed_at": "2026-11-07T17:15:55Z", "recovered": true, ...}
  ```

  `make oncall-verify` exit **0**.

- Incident `verification.status` / `verification.observed_at`: `verified` / `2026-11-07T17:15:55Z`,
  after the fixed build started. **Note on wording:** issue #63 AC4 says `passed`, but
  `response.schema.json` (the frozen T7.2 contract) allows `verified | failed | not_run`; the record
  uses the schema's `verified` and this log records the mapping rather than writing an invalid value.
- `/healthz` at recovery: `{"status":"ok","db":"ok"}`. `/api/invariants`: `{"ok": true, "violations": []}`.

## AC5 — record, impact and detection gap

- `incidents/<incident-id>.md`: `on-call-engineer/incidents/stockroom-order-error-rate-high-a697e0be6f0f-1794071189.md`,
  rendered from the validated JSON; it carries alert (name, threshold and window from the packet),
  user impact with numbers, evidence inspected, hypothesis, action taken, files changed, PR URL,
  verification of recovery and the detection gap, in that order.
- User impact with numbers: order-journey 5xx reached 44.4% over the 5m window (24 of 54 local
  requests, threshold 5%); every fulfil of an order that took the last free units returned 500, the
  order stayed confirmed, its reservation was never released and the units never shipped.
- Detection gap: none for detection (the rule fired about a minute after the failures began); the gap
  is test coverage — no existing test fulfils an order that takes the last free units.
- Files changed by the fix: `backend/api/orders.py` (one atomic counter update; 18 lines changed in
  the commit's stat) and the new regression test.

## Human sign-off

- Reviewer (human): cancinoray
- Verdict (`approve` / `reject`): approve
- Fix-PR approval or comment URL: https://github.com/cancinoray/stockroom/pull/67#issuecomment-6711009920
- Reviewed at (UTC): 2026-11-07T17:59:03Z
- Notes / follow-ups: Drill evidence reviewed and approved. The deterministic drill responder is accepted (the `claude` CLI could not authenticate under the isolated HOME); the record uses the frozen schema's `verified` for the issue's `passed`; PR #67 is evidence only and must not be merged to `main`. AC6 cleanup and AC7's QA revert check remain.

## AC6 — cleanup and landing

- Fix PR closed (not merged) at: `<unfilled>` — PR #67 is open for QA's AC7 revert check; do not
  merge it, its base is the drill branch.
- `drill/p7-fulfil-last-units-500` deleted at: `<unfilled>` — left for QA inspection.
- `oncall/stockroom-order-error-rate-high-a697e0be6f0f-1794071189` deleted at: `<unfilled>` — left
  for QA's AC7 revert check; it is the PR head.
- Docs/ops PR URL carrying this harness and the incident record to `main`:
  https://github.com/cancinoray/stockroom/pull/66
- `make lint` and `make test` on the docs/ops PR: `make lint` clean; `make test` 291 unit + 91
  frontend passed (1 skipped); `make test-integration` 208 passed on the drill base.
- `make lint` and `make test` on `main` after the QA merge, with the merge commit: `<unfilled>` —
  QA post-merge check.
- Commit on `origin/main` that contains any of `bug.patch`'s product change: none — `main` is
  `5f957b5`; the product change exists only in `bug.patch` and the drill branch, never on `main`.
