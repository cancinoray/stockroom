# Local observability stack

Stockroom's telemetry runs on a local Docker Compose stack started by exactly one command:

```bash
make observability
```

It starts the existing `app` and `db` plus an OpenTelemetry collector, Prometheus, Loki, Tempo,
Alloy and Grafana. The app exports OTLP/HTTP to the collector, Prometheus scrapes the collector's
Prometheus exporter, Alloy ships the app's JSON stdout lines to Loki, and Grafana is provisioned
from files — datasources, dashboard provider and the **Stockroom order journey** dashboard. Every
request-data panel links to the Grafana trace search for the trace id that produced it.

Stop the stack with:

```bash
make observability-down
```

Both targets read one file list, defined once in the `Makefile`:

```make
OBSERVABILITY_FILES = -f compose.yaml -f compose.observability.yaml $(if $(wildcard compose.override.yaml),-f compose.override.yaml)
```

`compose.override.yaml` is machine-local and untracked. The Makefile appends it only when it exists,
so `make observability` publishes the same `app` port as `make dev`: `8000` on a clean checkout,
`18000` where the local override remaps it. No environment-prefixed or profile-only command is an
equivalent; use `make observability`.

## Ports — the contract

| Compose service | Image                                  | Published on host                         | Role                                                         |
| --------------- | -------------------------------------- | ----------------------------------------- | ------------------------------------------------------------ |
| `app`           | `stockroom-app:local` (or `STOCKROOM_IMAGE`) | `8000` clean / `18000` with the local override | the app; exports OTLP/HTTP to the collector                  |
| `db`            | `postgres:16`                          | none                                      | unchanged; never restated by the overlay                     |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.164.0` | `4318` (OTLP/HTTP), `4317` (OTLP/gRPC) | receives OTLP; traces → Tempo, metrics → `:8889`             |
| `prometheus`    | `prom/prometheus:v3.16.0`              | `9090`                                    | scrapes `otel-collector:8889`; never scrapes the app         |
| `tempo`         | `grafana/tempo:2.10.10`                | `3200`                                    | trace store; OTLP `4317`/`4318` are internal only            |
| `loki`          | `grafana/loki:3.6.20`                  | `3100`                                    | log store                                                    |
| `alloy`         | `grafana/alloy:v1.21.3`                | none                                      | discovers the `app` container logs and pushes them to Loki   |
| `grafana`       | `grafana/grafana:13.2.5`               | `3000`                                    | dashboards, Explore, trace search                            |

Fixed details:

- The app's OTLP target is `http://otel-collector:4318`. `4317` is published only so a native
  `make run` backend can export over gRPC; the compose `app` uses `4318`.
- The collector's Prometheus exporter listens on `:8889` inside the compose network. It is never
  published: `curl localhost:8889` fails from the host.
- Prometheus does not scrape the app. T6.1 gives the app no metrics endpoint; the path is
  app → OTLP → collector → `:8889` → Prometheus.
- Logs do not travel over OTLP. The app writes JSON to stdout; Alloy reads the Docker log stream.
- Ports are fixed. If one is busy on your machine, change the local `compose.override.yaml` (or your
  own local override) and record the deviation; the contract above does not move.

## Pinned images

Every observability image is pinned by tag **and** digest. There is no `latest` and no floating tag.
The tags and digests are the values in `compose.observability.yaml`:

| Image                                        | Tag        | Digest                                                                 |
| -------------------------------------------- | ---------- | ---------------------------------------------------------------------- |
| `otel/opentelemetry-collector-contrib`       | `0.164.0`  | `sha256:340c9ca6a36617084c6661bdc4f0fe92b7cda5a805d61673ec8db375fddc522b` |
| `prom/prometheus`                            | `v3.16.0`  | `sha256:e04987641b57704f408e31f6373ba4138ecf27cb4a165d24aabb6c38fddd0f06` |
| `grafana/loki`                               | `3.6.20`   | `sha256:be040ec94865dabe4821ce1c0f109452bd4b5acb566ae376672696eb43caedb7` |
| `grafana/tempo`                              | `2.10.10`  | `sha256:12b0820f13ffa10ce956b6e9acc3b03f3cffded99109be6cc09d106fe56e5d38` |
| `grafana/alloy`                              | `v1.21.3`  | `sha256:8ab871206bd2d8f89277f53abffee5f452a293980788d52f85fa183a87a505a4` |
| `grafana/grafana`                            | `13.2.5`   | `sha256:9f7aa1e1e3246aade5792d35a738049f7f32f89cd51d1956cf426a4e86268a84` |

**For T6.3 (#57):** the Prometheus image tag for `promtool check rules` is **`v3.16.0`**. The
collector is **`0.164.0`**.

After the first pull the profile starts without outbound network access. Nothing here calls a hosted
service.

## Layout

```
compose.observability.yaml                 the overlay: six profiled services + app telemetry env
observability/
  README.md                                this file
  otel-collector/config.yaml               OTLP receivers, Tempo exporter, Prometheus exporter
  prometheus/prometheus.yml                scrapes otel-collector:8889 only
  loki/loki.yaml                           single-binary, filesystem, no auth
  tempo/tempo.yaml                         local trace store, OTLP receivers internal
  alloy/config.alloy                       Docker log discovery -> Loki
  grafana/provisioning/datasources/        Prometheus, Loki and Tempo with fixed UIDs
  grafana/provisioning/dashboards/         the file-based dashboard provider
  dashboards/order-journey.json            the provisioned dashboard
```

`compose.observability.yaml` adds services and gives `app` its telemetry environment. It does not
restate `app.ports`, the `db` service or the `stockroom-db` volume: Compose merges `ports` by
concatenation, so restating them would publish twice. The overlay inherits `name: stockroom` from
`compose.yaml`, so `make observability` and `make dev` re-create the same `app` container in place.

## How the pieces connect

```
app --OTLP/HTTP 4318--> otel-collector --OTLP/gRPC 4317--> tempo
                              |
                              +--prometheus exporter :8889--> prometheus --> grafana
app stdout (JSON lines) --Docker socket--> alloy --> loki:3100 --> grafana
```

- **Traces.** T6.1 exports OTLP/HTTP. The collector forwards spans to Tempo over the compose network;
  Tempo's OTLP ports are never published.
- **Metrics.** The collector's `prometheus` exporter sets
  `resource_to_telemetry_conversion.enabled: true`, so the resource attributes `service.name`,
  `service.version` and `deployment.environment` become the `service_name`, `service_version` and
  `deployment_environment` labels. T6.3 templates its `environment` and `version` on exactly those.
  The five metric names are fixed by T6.1: `stockroom_orders_placed_total`,
  `stockroom_orders_failed_total`, `stockroom_http_request_duration_seconds`,
  `stockroom_reservation_conflicts_total`, `stockroom_stock_invariant_drift`.
- **Logs.** Alloy discovers the `app` container through the Docker socket, keeps only that container,
  and pushes its unchanged JSON lines to Loki. The `trace_id` stays in the JSON body, so LogQL can
  filter on it and Grafana renders it as a link into Tempo.

### Alloy's Docker socket is local-only

`/var/run/docker.sock` is mounted **read-only**, and only in `compose.observability.yaml`. It is the
local log-discovery mechanism. It must never be added to `compose.yaml`, CI, a published image or a
deployed host, and the app never talks to the Docker API. The socket mount is not part of any
deployment.

## Start, inspect, stop

```bash
make observability
docker compose -f compose.yaml -f compose.observability.yaml --profile observability ps
```

On a machine with the untracked local override, append `-f compose.override.yaml` to every inspection
command, or use the `make` targets. Status is reported per service and not invented: `app` reports
`healthy` from the image's own `HEALTHCHECK`; `otel-collector` and `alloy` ship no healthcheck, so
they are accepted as **running** plus their own readiness checks below.

```bash
# Collector readiness (contrib image has no healthcheck): 13133 is internal.
docker compose -f compose.yaml -f compose.observability.yaml --profile observability \
  exec prometheus wget -qO- http://otel-collector:13133/

# Alloy readiness: 12345 is internal.
docker compose -f compose.yaml -f compose.observability.yaml --profile observability \
  exec app python -c "import urllib.request; print(urllib.request.urlopen('http://alloy:12345/-/ready').read().decode())"

# The Prometheus exporter answers inside the network and not on the host.
docker compose -f compose.yaml -f compose.observability.yaml --profile observability \
  exec prometheus wget -qO- http://otel-collector:8889/metrics
curl -s localhost:8889/metrics   # must fail

curl -s localhost:3000/api/health
curl -s localhost:9090/-/healthy
curl -s localhost:3100/ready
curl -s localhost:3200/ready

curl -s localhost:3000/api/datasources
curl -s localhost:3000/api/dashboards/uid/stockroom-order-journey
```

`make observability-down` stops the whole project with a plain `down` (no `-v`), so the
`stockroom-db` volume and the observability volumes survive. A fresh Grafana volume is not needed to
get the dashboard: it is read from `/etc/grafana/dashboards` at startup.

## The dashboard and trace links

- **UID:** `stockroom-order-journey`
- **URL:** `http://localhost:3000/d/stockroom-order-journey`
- **API check:** `GET http://localhost:3000/api/dashboards/uid/stockroom-order-journey` returns `200`
  on a fresh volume, with no import step.

Templating variables: `datasource` (Prometheus), `tempo_datasource` (Tempo), `environment` (from the
`deployment_environment` label) and `grafana_url` (a textbox whose default is
`http://localhost:3000`). Panels reference the datasource variables, never a literal UID.

Panels: orders placed, orders failed by reason, p95 request latency, reservation conflicts and
invariant drift. The four request-data panels carry a **Open trace for this request** link. The link
is the Grafana trace search:

```
${grafana_url}/explore?left=<percent-encoded Explore payload>
```

The payload selects the Tempo datasource (`${tempo_datasource}`) and queries by trace id
(`queryType: "traceId"`, `query: "${__data.fields.traceID}"`). Expanding the four variables with
real values leaves a well-formed URL with no `${...}` left. For example, with trace id
`4bf92f3577b34da6a3ce929d0e0e4736`:

```bash
curl -s "http://localhost:3000/explore?left=%7B%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queryType%22%3A%22traceId%22%2C%22query%22%3A%224bf92f3577b34da6a3ce929d0e0e4736%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D"
```

The same trace id is in the request's JSON log line, so the Loki query for the same request returns
the line and the link renders it as a jump into Tempo.

## Pointing the same command at Grafana Cloud — **optional, not exercised in P6**

The local stack is the verified path. Cloud is an environment-variable-only option: no file edit, no
second command. The only exporter inputs remain `OTEL_EXPORTER_OTLP_ENDPOINT` and
`OTEL_EXPORTER_OTLP_HEADERS`, which the overlay passes through with local defaults.

The human steps (a human gate, `_docs/handoff.md` O4; never committed):

1. Create the Grafana Cloud stack and an OTLP token in its UI.
2. Export both variables in the shell that runs the one command. The value is the operator's,
   supplied per stack; it is never written to a file in this repository.

   ```bash
   export OTEL_EXPORTER_OTLP_ENDPOINT="https://otlp-gateway-<region>.grafana.net/otlp"
   export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20<operator-supplied-token>"
   make observability
   ```

3. The local Prometheus, Loki, Tempo and Grafana still run; they are just no longer the destination
   of the app's traces and metrics. There is no Cloud dashboard, retention or notification setup in
   this repository, and no P6 acceptance criterion requires one.

## Troubleshooting

- **A port is busy.** Change the host side in your local (untracked) override and record it. Do not
  add a `*_PORT` variable or a fallback to the contract.
- **`app` restarts after `make observability`.** The app needs the `db` healthcheck; Compose merges
  the base `depends_on` with the overlay's collector dependency. Check `docker compose logs app`
  and `docker compose logs otel-collector`.
- **Grafana shows no data.** Confirm `curl localhost:9090/api/v1/query?query=stockroom_orders_placed_total`
  returns a series; if not, place an order through the app first and wait one export interval
  (5 seconds).
- **No logs in Loki.** Confirm the Alloy container can read the Docker socket and that the app
  container name matches `stockroom-app*`; the relabel rule keeps only that container.
