# StockroomOrderErrorRateHigh

Problem+json 5xx responses on the order journey are above 5% of all order-journey requests.

- **Severity:** critical
- **Service:** `stockroom` (environment and version come from the metric's
  `deployment_environment` and `service_version` labels)
- **Owner:** `stockroom-on-call` — placeholder, to be replaced by a human
- **Window:** 5m rate, `for: 1m`
- **Dashboard:** <http://localhost:3000/d/stockroom-order-journey>

## The rule

```yaml
alert: StockroomOrderErrorRateHigh
for: 1m
labels:
  severity: critical
  service: stockroom
  environment: "{{ $labels.deployment_environment }}"
  version: "{{ $labels.service_version }}"
  owner: stockroom-on-call
  dashboard_url: http://localhost:3000/d/stockroom-order-journey
```

```promql
(
  sum by (service_name, service_version, deployment_environment) (
    rate(stockroom_http_request_duration_seconds_count{http_route=~"/api/orders(/.*)?", http_response_status_code=~"5.."}[5m])
  )
  /
  sum by (service_name, service_version, deployment_environment) (
    rate(stockroom_http_request_duration_seconds_count{http_route=~"/api/orders(/.*)?"}[5m])
  )
) > 0.05
```

The numerator counts only 5xx status codes; every error response from this app is
`application/problem+json`, with the request's `trace_id` in the body. The
denominator counts every request to `POST /api/orders`,
`POST /api/orders/{id}/cancel` and `POST /api/orders/{id}/fulfil`. 4xx responses
(validation, `409 insufficient_stock`, `409 invalid_transition`) are part of the
denominator and never of the numerator.

## User impact

Users placing, cancelling or fulfilling orders see a problem+json error instead of
a confirmed order — at 5% or more of order-journey requests over five minutes,
including every request when the database connection is lost.

## First three checks (read-only)

1. Confirm the alert is firing and see its current value:

   ```bash
   curl -s localhost:9090/api/v1/alerts | python3 -m json.tool
   ```

2. Read the ratio directly from Prometheus (the same expression, without the
   threshold):

   ```bash
   curl -sG localhost:9090/api/v1/query --data-urlencode 'query=sum by (service_version, deployment_environment) (rate(stockroom_http_request_duration_seconds_count{http_route=~"/api/orders(/.*)?", http_response_status_code=~"5.."}[5m])) / sum by (service_version, deployment_environment) (rate(stockroom_http_request_duration_seconds_count{http_route=~"/api/orders(/.*)?"}[5m]))' | python3 -m json.tool
   ```

3. Find the failing requests in the app log (Loki), then open one trace id in
   Tempo:

   ```bash
   curl -sG localhost:3100/loki/api/v1/query_range --data-urlencode 'query={container=~"stockroom-app.*"} | json | status_code >= 500' --data-urlencode 'limit=5' | python3 -m json.tool
   ```

The log line carries `trace_id`; open it in the Tempo trace search:
<http://localhost:3000/explore?left=%7B%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queryType%22%3A%22traceId%22%2C%22query%22%3A%22TRACE_ID%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D>
(replace `TRACE_ID` with the id from the log line).

## Recovery signal

`curl -s localhost:9090/api/v1/alerts` no longer lists
`StockroomOrderErrorRateHigh`, and the ratio query from check 2 is below `0.05`.
The dashboard's **Orders placed** panel resumes while **Orders failed by reason**
stops growing. The app's own log lines for the order routes return `201`/`409`
again instead of `500`.

## Threshold

- **Chosen threshold:** `0.05` (5% of order-journey requests returning 5xx, over a
  5m window, `for: 1m`).
- **Observed in the recorded local firing (2026-11-06):** `1.0` (100%) at the
  firing evaluation, while `db` was stopped and 60 order requests each returned a
  problem+json 500. Pending at `19:21:20Z`, firing at `19:22:21Z`, resolved at
  `19:22:46Z` after `db` restarted and 1500 `409 insufficient_stock` responses
  were counted in the denominator only.
- **4xx does not cross it:** a baseline burst of 20 `409 insufficient_stock`
  responses produced no numerator series at all; the 1500-response post-recovery
  burst drove the ratio below the threshold instead of into it.
- **Why this value:** it separates "a few users hit a validation error" (4xx,
  never counted) from "a meaningful share of orders cannot be placed", and it is
  far above the zero-error baseline, so it is not an artificially low trigger.
- **Resolution limit:** a 5xx burst shorter than one scrape/export interval can
  be invisible to `rate` on a brand-new series; the recorded run therefore spread
  60 failures over 60s. Sustained incidents are not affected.

## Autonomy and escalation

The on-call agent may investigate read-only against this local stack and may open
a PR against a throwaway branch; it may not merge, deploy, or run SQL against
production. Escalate to a human for anything outside that boundary.

- Who may act: [_docs/process.md §2](../process.md#2-permissions)
- Escalation routes: [_docs/process.md §10](../process.md#10-escalation)
- Investigation loop and its guardrails:
  [.agents/skills/investigate-alert/SKILL.md](../../.agents/skills/investigate-alert/SKILL.md)

A production firing routes to the on-call agent under
`on-call-engineer/autonomy-policy.yaml`; this runbook never points anyone at a
production database.
