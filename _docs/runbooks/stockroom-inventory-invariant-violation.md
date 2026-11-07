# InventoryInvariantViolation

A cached stock counter disagrees with the append-only movements ledger.

- **Severity:** critical
- **Service:** `stockroom` (environment and version come from the metric's
  `deployment_environment` and `service_version` labels)
- **Owner:** `stockroom-on-call` — placeholder, to be replaced by a human
- **Window:** the last reported drift check (the gauge is refreshed every 30s),
  `for: 1m`
- **Dashboard:** <http://localhost:3000/d/stockroom-order-journey>

## The rule

```yaml
alert: InventoryInvariantViolation
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
label_replace(
  stockroom_stock_invariant_drift_ratio,
  "__name__", "stockroom_stock_invariant_drift",
  "__name__", ".*"
) > 0
```

T6.1 creates the gauge with unit `1`, and the collector's Prometheus exporter
follows the Prometheus convention by exporting it as
`stockroom_stock_invariant_drift_ratio`. `_docs/domain.md` §4 and the dashboard
use the un-suffixed name, so the rule evaluates the exported series under the
documented name with one `label_replace`; the alert therefore reports
`stockroom_stock_invariant_drift`. The gauge is T6.1's observable gauge: the number
of violations returned by the same check that `GET /api/invariants` reports. Zero
is the clean state; any value above zero is a violated state per
[`_docs/domain.md` §4](../domain.md#4-invariants-as-executable-checks). The gauge
carries the metric's own `service_name`, `service_version` and
`deployment_environment` labels, so nothing is aggregated away.

> Known doc gap: `_docs/domain.md` §4 and the dashboard's invariant panel cite the
> un-suffixed name. Aligning them is a follow-up outside issue #57's write scope.

## User impact

Operators can no longer trust the stock figures the app shows — a cached
`on_hand` or `reserved` value disagrees with the ledger, so availability and
low-stock decisions are based on a wrong number until the cache is reconciled
from the movements.

## First three checks (read-only)

1. Confirm the alert is firing and see the reported value:

   ```bash
   curl -s localhost:9090/api/v1/alerts | python3 -m json.tool
   ```

2. Read the exported gauge directly from Prometheus:

   ```bash
   curl -sG localhost:9090/api/v1/query --data-urlencode 'query=stockroom_stock_invariant_drift_ratio' | python3 -m json.tool
   ```

3. Ask the app which rule and SKU disagreed — the endpoint reports the rule id,
   the SKU and the two numbers, and never returns 500:

   ```bash
   curl -s localhost:8000/api/invariants | python3 -m json.tool
   ```

On a machine with the untracked `compose.override.yaml`, the app is published on
`18000` instead of the contract's `8000`; use that port for check 3 and record the
deviation.

## Traces and logs

The app logs one JSON warning per new violation. Find it in Loki and open its
`trace_id` in the Tempo trace search:

```bash
curl -sG localhost:3100/loki/api/v1/query_range --data-urlencode 'query={container=~"stockroom-app.*"} |= "invariant drift"' --data-urlencode 'limit=5' | python3 -m json.tool
```

<http://localhost:3000/explore?left=%7B%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queryType%22%3A%22traceId%22%2C%22query%22%3A%22TRACE_ID%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D>
(replace `TRACE_ID`).

## Confirming the drift is real (read-only SQL, local only)

The ledger is the truth; the cache is derived. This query shows the cached
counters next to the ledger sum for the SKU named by the endpoint:

```bash
docker compose -f compose.yaml -f compose.observability.yaml --profile observability exec db psql -U stockroom -d stockroom -c "SELECT s.sku, s.on_hand AS cached_on_hand, COALESCE(SUM(m.delta_on_hand), 0) AS ledger_on_hand, s.reserved AS cached_reserved, COALESCE(SUM(m.delta_reserved), 0) AS ledger_reserved FROM stock s LEFT JOIN movements m USING (warehouse_id, sku) WHERE s.sku = 'SKU-1001' GROUP BY s.warehouse_id, s.sku, s.on_hand, s.reserved;"
```

Never hand-fix a counter in production and never `UPDATE`/`DELETE` a movement.
On the disposable local stack a labelled direct-SQL corruption is the accepted
way to rehearse this alert (see the recorded firing below); it is not a product
path.

## Recovery signal

`curl -s localhost:9090/api/v1/alerts` no longer lists
`InventoryInvariantViolation`, the gauge query from check 2 returns `0`, and
`GET /api/invariants` reports `violations: []`. The dashboard's **Invariant
drift** panel returns to zero.

## Threshold

- **Chosen threshold:** anything above `0` violations, evaluated for `1m`.
- **Observed in the recorded local firing (2026-11-06):** `1` violation at the
  firing evaluation, after `on_hand` for `SKU-3301` was advanced by 5 without a
  movement. Pending at `19:19:20Z`, firing at `19:20:23Z`, cache restored from
  the ledger at `19:20:28Z`, resolved at `19:21:03Z` with the gauge back at `0`.
- **Recorded corruption (local, disposable database only):**

  ```bash
  docker compose -f compose.yaml -f compose.observability.yaml --profile observability exec -T db psql -U stockroom -d stockroom -c "UPDATE stock SET on_hand = on_hand + 5 WHERE sku = 'SKU-3301';"
  ```

  and the repair from the ledger:

  ```bash
  docker compose -f compose.yaml -f compose.observability.yaml --profile observability exec -T db psql -U stockroom -d stockroom -c "UPDATE stock s SET on_hand = (SELECT COALESCE(SUM(m.delta_on_hand), 0) FROM movements m WHERE m.warehouse_id = s.warehouse_id AND m.sku = s.sku) WHERE s.sku = 'SKU-3301';"
  ```

  `_docs/domain.md` §3 says tests create corrupt rows with a dedicated `admin`
  role. No such role exists in this repository or its compose stack, so the
  drill used the local `stockroom` database owner through psql and is labelled as
  test corruption. The doc is ahead of the code; a dedicated test role is a
  follow-up. No product endpoint was added for failure injection.

- **Why this value:** the domain treats any disagreement between the cache and
  the ledger as a correctness fault, so there is no tolerable non-zero band.

## Autonomy and escalation

The on-call agent may read the endpoint, the ledger and the traces, and may open
a PR with a repro; it may not merge, deploy, or run SQL against production. A
real invariant violation is a data-correctness incident: escalate to a human
before any reconciliation, because the ledger trail is the evidence.

- Who may act: [_docs/process.md §2](../process.md#2-permissions)
- Escalation routes: [_docs/process.md §10](../process.md#10-escalation)
- Investigation loop and its guardrails:
  [.agents/skills/investigate-alert/SKILL.md](../../.agents/skills/investigate-alert/SKILL.md)

A production firing routes to the on-call agent under
`on-call-engineer/autonomy-policy.yaml`; this runbook never points anyone at a
production database.
