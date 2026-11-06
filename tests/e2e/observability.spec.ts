import { expect, test } from "@playwright/test";

/**
 * AC2, AC4, AC5 and AC6 against a running local observability stack.
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
});
