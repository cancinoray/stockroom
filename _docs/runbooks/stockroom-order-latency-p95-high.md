# StockroomOrderLatencyP95High

The 95th percentile of order-journey request duration is above 2 seconds.

- **Severity:** warning
- **Service:** `stockroom` (environment and version come from the metric's
  `deployment_environment` and `service_version` labels)
- **Owner:** `stockroom-on-call` — placeholder, to be replaced by a human
- **Window:** 5m rate over the request-duration histogram, `for: 1m`
- **Dashboard:** <http://localhost:3000/d/stockroom-order-journey>

## The rule

```yaml
alert: StockroomOrderLatencyP95High
for: 1m
labels:
  severity: warning
  service: stockroom
  environment: "{{ $labels.deployment_environment }}"
  version: "{{ $labels.service_version }}"
  owner: stockroom-on-call
  dashboard_url: http://localhost:3000/d/stockroom-order-journey
```

```promql
histogram_quantile(
  0.95,
  sum by (le, service_name, service_version, deployment_environment) (
    rate(stockroom_http_request_duration_seconds_bucket{http_route=~"/api/orders(/.*)?"}[5m])
  )
) > 2
```

The histogram is T6.1's `stockroom_http_request_duration_seconds`, with its fixed
bucket set documented in `backend/telemetry.py`. Only the order routes are
selected. `service_version` and `deployment_environment` stay in the `by` clause
so the rule labels survive the aggregation.

## User impact

One in twenty order-journey requests takes longer than 2 seconds — an operator
waiting to place, cancel or fulfil an order sees the screen hang rather than
fail, often while the database is slow or blocked.

## First three checks (read-only)

1. Confirm the alert is firing and see the current percentile:

   ```bash
   curl -s localhost:9090/api/v1/alerts | python3 -m json.tool
   ```

2. Read p95 directly from Prometheus (the same expression, without the
   threshold):

   ```bash
   curl -sG localhost:9090/api/v1/query --data-urlencode 'query=histogram_quantile(0.95, sum by (le, service_version, deployment_environment) (rate(stockroom_http_request_duration_seconds_bucket{http_route=~"/api/orders(/.*)?"}[5m])))' | python3 -m json.tool
   ```

3. Find one slow request and its trace id in the app log (Loki), keeping only
   lines whose `duration_ms` is high:

   ```bash
   curl -sG localhost:3100/loki/api/v1/query_range --data-urlencode 'query={container=~"stockroom-app.*"} | json | duration_ms > 1000' --data-urlencode 'limit=5' | python3 -m json.tool
   ```

Open the `trace_id` from that line in the Tempo trace search:
<http://localhost:3000/explore?left=%7B%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queryType%22%3A%22traceId%22%2C%22query%22%3A%22TRACE_ID%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D>
(replace `TRACE_ID`). The database span in that trace shows where the time went.

## Recovery signal

`curl -s localhost:9090/api/v1/alerts` no longer lists
`StockroomOrderLatencyP95High`, and the p95 query from check 2 is below `2`
seconds once the five-minute window has drained. The dashboard's **p95 request
latency** panel returns to its normal sub-second band.

## Threshold

- **Chosen threshold:** `2` seconds at p95, over a 5m window, `for: 1m`.
- **Observed in the recorded local firing (2026-11-06):** p95 `9.08` seconds at
  the firing evaluation, after `db` was paused for 9s while 30 order requests
  were in flight. Pending at `19:12:30Z`, firing at `19:13:32Z`, resolved at
  `19:14:05Z` once 800 fast `409 insufficient_stock` responses pushed the slow
  requests below 5% of the window.
- **Normal baseline:** p95 is roughly `0.02`–`0.05` seconds on the local stack.
- **Why this value:** 2s is the point where an operator calls the screen slow,
  and it is two orders of magnitude above the healthy local baseline, so the
  rule cannot fire on ordinary jitter.
- **Window mix:** the percentile is over all order-journey requests, including
  4xx. A short stall inside a window dominated by fast 4xx responses can stay
  below p95; the recorded run therefore used a realistic sustained stall.

## Autonomy and escalation

Read-only investigation on the local stack is allowed; a fix is a PR against a
throwaway branch and never a merge, deploy or production write. Escalate when the
cause is outside the app (host, database, network).

- Who may act: [_docs/process.md §2](../process.md#2-permissions)
- Escalation routes: [_docs/process.md §10](../process.md#10-escalation)
- Investigation loop and its guardrails:
  [.agents/skills/investigate-alert/SKILL.md](../../.agents/skills/investigate-alert/SKILL.md)

A production firing routes to the on-call agent under
`on-call-engineer/autonomy-policy.yaml`; this runbook never points anyone at a
production database.
