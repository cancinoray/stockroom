# Incident stockroom-order-error-rate-high-324f01034b2a-1794026992

## Alert

- Name: `StockroomOrderErrorRateHigh`
- Severity: critical
- Environment: development
- Version: 0.1.0
- Dashboard: http://localhost:3000/d/stockroom-order-journey
- Rule for: 1m

- Rule expr:

  ```promql
  (
    sum by (service_name, service_version, deployment_environment) (
      rate(stockroom_http_request_duration_seconds_count{http_route=~"/api/orders(/.*)?",
        http_response_status_code=~"5.."}[5m])
    )
    /
    sum by (service_name, service_version, deployment_environment) (
      rate(stockroom_http_request_duration_seconds_count{http_route=~"/api/orders(/.*)?"}[5m])
    )
  ) > 0.05
  ```

- Action: fix

## User impact

Fixture run: the AC7 harness exercises the runner, not a real incident.

## Evidence inspected

- evidence packet
- backend/domain/invariants.py

## Hypothesis

Fixture: the runner reaches a commit and a PR through the policy shims.

## Changes

- Files:
  - `backend/domain/invariants.py`
- Test: `tests/unit/test_invariants_public_api.py`
- Branch: `oncall/stockroom-order-error-rate-high-324f01034b2a-1794026992`
- Base ref: `main`
- Worktree: `worktrees/oncall-stockroom-order-error-rate-high-324f01034b2a-1794026992`
- Pull request: https://github.com/cancinoray/stockroom/pull/900

## Policy

- Policy: version `1`, policy sha256 `98e611454e8dd87406aba6cf87f02c6661c7aafa18b1fa7409338b2adc03f55b`
- Decisions:
  - `read.packet` -> allow (rule `read-packet`): The evidence packet is the input to the task.
  - `read.repo` -> allow (rule `read-repo`): Reading the isolated worktree is read-only for everything deployed.
  - `edit` -> allow (rule `edit-allowed`): Editing application and test code inside the worktree is the fix path.
  - `run.tests` -> allow (rule `run-tests`): make test-unit / make test-integration are local and touch no deployed system.
  - `git.commit` -> allow (rule `commit`): Commits belong on the responder's own branch, never on main.
  - `pr.create` -> allow (rule `pr-create`): gh pr create against the packet's recorded base is the only remote write.

## Verification

- Status: verified
- Observed at: not recorded
- Checks:
  - python3 -m pytest tests/unit/test_invariants_public_api.py

## Timing

- Started: 2026-11-07T06:22:34Z
- Ended: 2026-11-07T06:22:36Z
- Elapsed: 1.279s of a 600s budget

## Detection gap

Fixture: not assessed.

## Escalation

None: the responder did not escalate.

## Review

- Status: pending
- Notes: AC7 fixture run: verifies the runner, schema and rendering; not a diagnosis.

