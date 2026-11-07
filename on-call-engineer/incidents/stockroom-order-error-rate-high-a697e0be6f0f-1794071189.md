# Incident stockroom-order-error-rate-high-a697e0be6f0f-1794071189

## Alert

- Name: `StockroomOrderErrorRateHigh`
- Severity: critical
- Environment: development
- Version: 586031574acaf8d5e74d8b5de313bb464d5d43de
- Dashboard: http://localhost:3000/d/stockroom-order-journey
- Rule for: 60s

- Rule expr:

  ```promql
  (sum by (service_name, service_version, deployment_environment) (rate(stockroom_http_request_duration_seconds_count{http_response_status_code=~"5..",http_route=~"/api/orders(/.*)?"}[5m])) / sum by (service_name, service_version, deployment_environment) (rate(stockroom_http_request_duration_seconds_count{http_route=~"/api/orders(/.*)?"}[5m]))) > 0.05
  ```

- Action: fix

## User impact

Order-journey 5xx reached 44.4% over the rule's 5m window (24 of 54 local requests failed, threshold 5%). Every fulfil of an order that took the last free units of a SKU returned 500: the order stayed confirmed, its reservation was never released and the units never shipped.

## Evidence inspected

- evidence packet stockroom-order-error-rate-high-a697e0be6f0f-1794071189.json: alert StockroomOrderErrorRateHigh = 4.444444444444445e-01, rule for 60s, deployed version 586031574acaf8d5e74d8b5de313bb464d5d43de
- packet log samples: 20 5xx lines, selector {container=~"stockroom-app.*"} | json | status_code >= 500
- Tempo traces: 091d013fa54793eb99b9f4fe6da8d367 (7 spans: db.query SELECT, db.query SELECT, db.query SELECT, db.query INSERT, db.query UPDATE, db.query UPDATE, POST /api/orders/{id}/fulfil); 973b1f80abd0e22a818eb32b0a9b588c (7 spans: db.query SELECT, db.query SELECT, db.query SELECT, db.query INSERT, db.query UPDATE, db.query UPDATE, POST /api/orders/{id}/fulfil)
- reproduction against the running build: POST /api/orders for all 3 available SKU-8820 -> 201, then fulfil -> 500, cancel -> 200
- GET /api/invariants during the incident: {"ok": true, "violations": []}
- regression test tests/integration/test_fulfil_last_units_drill.py on the drill base: pytest exit 1
- regression test with the fix: pytest exit 0

## Hypothesis

_transition_order wrote stock.on_hand and then stock.reserved as two statements. The table check reserved <= on_hand is immediate, so the on_hand write alone is invalid whenever on_hand - qty < reserved, which is exactly available < qty: an order holding the last free units. The transaction rolls back and the request 500s.

## Changes

- Files:
  - `backend/api/orders.py`
  - `tests/integration/test_fulfil_last_units_drill.py`
- Test: `tests/integration/test_fulfil_last_units_drill.py`
- Branch: `oncall/stockroom-order-error-rate-high-a697e0be6f0f-1794071189`
- Base ref: `drill/p7-fulfil-last-units-500`
- Worktree: `worktrees/oncall-stockroom-order-error-rate-high-a697e0be6f0f-1794071189`
- Pull request: https://github.com/cancinoray/stockroom/pull/67

## Policy

- Policy: version `1`, policy sha256 `98e611454e8dd87406aba6cf87f02c6661c7aafa18b1fa7409338b2adc03f55b`
- Decisions:
  - `read.packet` -> allow (rule `read-packet`): The evidence packet is the input to the task.
  - `read.repo` -> allow (rule `read-repo`): Reading the isolated worktree is read-only for everything deployed.
  - `read.local_endpoint` -> allow (rule `read-local-endpoint`): Prometheus, Loki and the app on the local stack are the allowlisted read sources.
  - `git.worktree.create` -> allow (rule `worktree-create`): The isolated worktree is the only place the responder writes.
  - `git.branch.create` -> allow (rule `branch-create`): A throwaway oncall/ branch is the write path the process grants.
  - `run.tests` -> allow (rule `run-tests`): make test-unit / make test-integration are local and touch no deployed system.
  - `edit` -> allow (rule `edit-allowed`): Editing application and test code inside the worktree is the fix path.
  - `edit` -> allow (rule `edit-allowed`): Editing application and test code inside the worktree is the fix path.
  - `git.commit` -> allow (rule `commit`): Commits belong on the responder's own branch, never on main.
  - `git.push` -> allow (rule `push-feature`): A non-force push of a non-main branch is the review path.
  - `pr.create` -> allow (rule `pr-create`): gh pr create against the packet's recorded base is the only remote write.

## Verification

- Status: verified
- Observed at: 2026-11-07T17:15:55Z
- Checks:
  - before the fix (buggy build 586031574acaf8d5e74d8b5de313bb464d5d43de): verify-recovery.sh exit 1 at 2026-11-07T17:11:16Z -- alert_absent=false (1 alert listed), impact_below_threshold=false (1 series at or above 0.05), app_healthz=true, app_invariants=true
  - fixed build 0dbf4080782c5c043b3f7e0fdfdba2fff8bc3340 started at 2026-11-07T17:11:37Z; the rule's 5m window held the earlier failures until 2026-11-07T17:15:49Z, when the alert became absent
  - after the fix: verify-recovery.sh exit 0 at 2026-11-07T17:15:55Z -- alert_absent=true (0 listed), impact_below_threshold=true (0 series), app_healthz=true (status=ok db=ok), app_invariants=true (ok=True violations=0)

## Timing

- Started: 2026-11-07T17:10:43Z
- Ended: 2026-11-07T17:10:52Z
- Elapsed: 8.727s of a 600s budget

## Detection gap

None for detection: the 5% error-rate rule fired about a minute after the failures began. The gap is in coverage, not alerting: no existing test fulfils an order that takes the last free units, so only the alert caught it.

## Escalation

None: the responder did not escalate.

## Review

- Status: pending
- Notes: Deterministic drill responder for issue #63 (commit 0dbf4080782c5c043b3f7e0fdfdba2fff8bc3340). Not an autonomous agent run: the claude CLI cannot authenticate under the isolated HOME and no model credential is passed to the child. The responder cannot sign off its own work.

