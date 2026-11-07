# Incident stockroom-order-latency-p95-high-7c1d2e9f4a5b-1794027100

## Alert

- Name: `StockroomOrderLatencyP95High`
- Severity: warning
- Environment: development
- Version: 0.1.0
- Dashboard: http://localhost:3000/d/stockroom-order-journey
- Rule for: 1m

- Rule expr:

  ```promql
  histogram_quantile(
    0.95,
    sum by (le, service_name, service_version, deployment_environment) (
      rate(stockroom_http_request_duration_seconds_bucket{http_route=~"/api/orders(/.*)?"}[5m])
    )
  ) > 2
  ```

- Action: escalate

## User impact

Not assessed: the run stopped before a diagnosis was reached.

## Evidence inspected

- evidence packet

## Hypothesis

The run stopped before a diagnosis: the responder exceeded the 2s budget and was killed

## Changes

- Files: none
- Test: not recorded
- Branch: not recorded
- Base ref: `main`
- Worktree: `worktrees/oncall-stockroom-order-latency-p95-high-7c1d2e9f4a5b-1794027100`
- Pull request: not recorded

## Policy

- Policy: version `1`, policy sha256 `98e611454e8dd87406aba6cf87f02c6661c7aafa18b1fa7409338b2adc03f55b`
- Decisions:
  - `escalate` -> escalate (rule `budget-exhausted`): The ten-minute budget is spent; a slow investigation is a second incident.

## Verification

- Status: not_run
- Observed at: not recorded
- Checks: none recorded

## Timing

- Started: 2026-11-07T06:22:47Z
- Ended: 2026-11-07T06:22:49Z
- Elapsed: 2.057s of a 2s budget

## Detection gap

Not assessed.

## Escalation

- Decision required: A human must take over StockroomOrderLatencyP95High: the responder exceeded the 2s budget and was killed
- Context: budget_exhausted

## Review

- Status: pending
- Notes: Automatic escalation written by the runner; no fix was attempted.

