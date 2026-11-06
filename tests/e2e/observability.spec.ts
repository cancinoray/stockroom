import { expect, test } from "@playwright/test";

/**
 * AC2, AC3, AC4, AC5, AC6 and AC7 against a running local observability stack.
 *
 * `make e2e` starts only app + db, so this file skips unless the stack from
 * `make observability` is already up and its Grafana URL is exported:
 *
 *   OBSERVABILITY_GRAFANA_URL=http://localhost:3000 \
 *     cd frontend && npx playwright test --config ../playwright.config.ts ../tests/e2e/observability.spec.ts
 *
 * The recorded run in the issue records the trace/log evidence separately; this
 * spec pins the provisioned objects and the expandable panel link.
 */

const app = (process.env.E2E_BASE_URL ?? "").replace(/\/+$/, "");
const grafana = (process.env.OBSERVABILITY_GRAFANA_URL ?? "").replace(/\/+$/, "");
const prometheus = (
  process.env.OBSERVABILITY_PROMETHEUS_URL ?? "http://localhost:9090"
).replace(/\/+$/, "");
const loki = (process.env.OBSERVABILITY_LOKI_URL ?? "http://localhost:3100").replace(
  /\/+$/,
  "",
);
const tempo = (process.env.OBSERVABILITY_TEMPO_URL ?? "http://localhost:3200").replace(
  /\/+$/,
  "",
);
const dashboardUid =
  process.env.OBSERVABILITY_DASHBOARD_UID ?? "stockroom-order-journey";

const PANEL_TITLES = [
  "Orders placed",
  "Orders failed by reason",
  "p95 request latency",
  "Reservation conflicts",
  "Invariant drift",
];

test.describe("local observability stack", () => {
  test.skip(
    !grafana,
    "set OBSERVABILITY_GRAFANA_URL to a running local observability stack",
  );

  test("readiness endpoints answer", async ({ request }) => {
    for (const [name, url] of Object.entries({
      grafana: `${grafana}/api/health`,
      prometheus: `${prometheus}/-/healthy`,
      loki: `${loki}/ready`,
      tempo: `${tempo}/ready`,
    })) {
      const response = await request.get(url);
      expect(response.ok(), `${name} at ${url}`).toBe(true);
    }
  });

  test("the three datasources are provisioned from files", async ({ request }) => {
    const response = await request.get(`${grafana}/api/datasources`);
    expect(response.status()).toBe(200);

    const datasources = (await response.json()) as Array<{ uid: string; type: string }>;
    expect(datasources.map((datasource) => datasource.uid).sort()).toEqual([
      "loki",
      "prometheus",
      "tempo",
    ]);
  });

  test("the order-journey dashboard loads without an import step", async ({ request }) => {
    const response = await request.get(
      `${grafana}/api/dashboards/uid/${dashboardUid}`,
    );
    expect(response.status()).toBe(200);

    const body = (await response.json()) as {
      dashboard: { uid: string; panels: Array<{ title: string }> };
    };
    expect(body.dashboard.uid).toBe(dashboardUid);
    const titles = body.dashboard.panels.map((panel) => panel.title);
    for (const title of PANEL_TITLES) {
      expect(titles, title).toContain(title);
    }
  });

  test("a request panel link expands to a well-formed Explore URL", async ({
    request,
  }) => {
    const response = await request.get(
      `${grafana}/api/dashboards/uid/${dashboardUid}`,
    );
    expect(response.status()).toBe(200);

    const body = (await response.json()) as {
      dashboard: {
        panels: Array<{ title: string; links?: Array<{ url: string }> }>;
      };
    };
    const panel = body.dashboard.panels.find((item) => item.title === "Orders placed");
    expect(panel?.links?.length, "Orders placed has a trace link").toBeTruthy();

    const sample: Record<string, string> = {
      grafana_url: grafana,
      tempo_datasource: "tempo",
      environment: "development",
      "__data.fields.traceID": "4bf92f3577b34da6a3ce929d0e0e4736",
    };
    let expanded = panel!.links![0].url;
    for (const [name, value] of Object.entries(sample)) {
      expanded = expanded.split(`\${${name}}`).join(value);
    }

    expect(expanded).not.toContain("${");
    const explore = await request.get(expanded);
    expect(explore.status()).toBe(200);
    expect(explore.headers()["content-type"]).toContain("text/html");
  });

  test("resource attributes survive into Prometheus after a real order", async ({
    request,
  }) => {
    test.skip(!app, "set E2E_BASE_URL to the running app");
    const stockResponse = await request.get(`${app}/api/stock`);
    expect(stockResponse.ok()).toBe(true);
    const stock = (await stockResponse.json()) as Array<{ sku: string; available: number }>;
    const sku = [...stock].sort((a, b) => b.available - a.available)[0];
    test.skip(!sku || sku.available < 1, "no stock available to place an order");

    const order = await request.post(`${app}/api/orders`, {
      data: {
        customer_ref: `QA-OBS-AC3-${Date.now() % 100_000}`,
        lines: [{ sku: sku.sku, qty: 1 }],
      },
    });
    expect(order.status()).toBe(201);

    const versionResponse = await request.get(`${app}/api/version`);
    const version = (await versionResponse.json()) as { version: string };

    let series:
      | { metric: Record<string, string>; value: [number, string] }
      | undefined;
    for (let attempt = 0; attempt < 30 && !series; attempt += 1) {
      const response = await request.get(`${prometheus}/api/v1/query`, {
        params: { query: "stockroom_orders_placed_total" },
      });
      expect(response.ok()).toBe(true);
      const body = (await response.json()) as {
        data: {
          result: Array<{ metric: Record<string, string>; value: [number, string] }>;
        };
      };
      series = body.data.result.find((entry) => entry.metric.service_name);
      if (!series) {
        await new Promise((resolve) => setTimeout(resolve, 1_000));
      }
    }

    expect(series, "stockroom_orders_placed_total reached Prometheus").toBeTruthy();
    expect(series!.metric.service_name).toBe("stockroom");
    expect(series!.metric.deployment_environment).toBe("development");
    expect(series!.metric.service_version).toBe(version.version);
  });

  test("the order log line carries the trace id Tempo returns", async ({ request }) => {
    test.skip(!app, "set E2E_BASE_URL to the running app");
    const stockResponse = await request.get(`${app}/api/stock`);
    expect(stockResponse.ok()).toBe(true);
    const stock = (await stockResponse.json()) as Array<{ sku: string; available: number }>;
    const sku = [...stock].sort((a, b) => b.available - a.available)[0];
    test.skip(!sku || sku.available < 1, "no stock available to place an order");

    // Nanosecond timestamps: ms + six zeros, kept as a string to avoid float loss.
    const start = `${Date.now()}000000`;
    const order = await request.post(`${app}/api/orders`, {
      data: {
        customer_ref: `QA-OBS-AC7-${Date.now() % 100_000}`,
        lines: [{ sku: sku.sku, qty: 1 }],
      },
    });
    expect(order.status()).toBe(201);

    let traceId: string | undefined;
    for (let attempt = 0; attempt < 30 && !traceId; attempt += 1) {
      const response = await request.get(
        `${grafana}/api/datasources/proxy/uid/loki/loki/api/v1/query_range`,
        {
          params: {
            query: '{job="stockroom-app"} |= "POST /api/orders"',
            start,
            end: `${Date.now()}000000`,
            limit: "20",
            direction: "backward",
          },
        },
      );
      expect(response.ok()).toBe(true);
      const body = (await response.json()) as {
        data: {
          result: Array<{ values: Array<[string, string]> }>;
        };
      };
      for (const stream of body.data.result) {
        for (const [, line] of stream.values) {
          const entry = JSON.parse(line) as {
            logger?: string;
            route?: string;
            status_code?: number;
            trace_id?: string;
          };
          if (
            entry.logger === "backend.telemetry" &&
            entry.route === "/api/orders" &&
            entry.status_code === 201 &&
            entry.trace_id
          ) {
            traceId = entry.trace_id;
            break;
          }
        }
        if (traceId) break;
      }
      if (!traceId) {
        await new Promise((resolve) => setTimeout(resolve, 1_000));
      }
    }

    expect(traceId, "the order's JSON log line reached the provisioned Loki").toMatch(
      /^[0-9a-f]{32}$/,
    );

    // Tempo ingests a batch after the collector flushes; poll before judging.
    let tempoStatus = 0;
    let spanNames: string[] = [];
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const tempoResponse = await request.get(
        `${grafana}/api/datasources/proxy/uid/tempo/api/traces/${traceId}`,
      );
      tempoStatus = tempoResponse.status();
      if (tempoStatus === 200) {
        const trace = (await tempoResponse.json()) as {
          batches: Array<{ scopeSpans: Array<{ spans: Array<{ name: string }> }> }>;
        };
        spanNames = trace.batches.flatMap((batch) =>
          batch.scopeSpans.flatMap((scope) => scope.spans.map((span) => span.name)),
        );
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1_000));
    }
    expect(tempoStatus, "Tempo returned the trace for the log line's trace id").toBe(200);
    expect(
      spanNames,
      "Tempo holds the POST /api/orders span for that trace id",
    ).toContain("POST /api/orders");
  });

});
