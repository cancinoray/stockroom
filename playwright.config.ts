import type { PlaywrightTestConfig } from "@playwright/test";

/**
 * The config lives at the repo root, but Playwright is installed in
 * `frontend/`. `make e2e` therefore runs it from `frontend/` and exports
 * `NODE_PATH=<repo>/frontend/node_modules` so this file and the specs resolve
 * `@playwright/test` without a second install.
 *
 * `E2E_BASE_URL` runs the specs against a UI that is already up (the stack
 * startup in `tests/e2e/run-e2e.sh` is skipped). Without it, the e2e script
 * exports the disposable API target and a free UI port, and the `webServer`
 * below starts the frontend on that port with the e2e-only Vite config.
 */
const baseUrl = process.env.E2E_BASE_URL?.trim();
const apiTarget = process.env.E2E_API_TARGET;
const uiPort = process.env.E2E_UI_PORT;

if (!baseUrl && (!apiTarget || !uiPort)) {
  throw new Error(
    "Run this through `make e2e`, or set E2E_BASE_URL to an already-running UI.",
  );
}

const config: PlaywrightTestConfig = {
  testDir: "./tests/e2e",
  // The specs mutate one seeded database, in a fixed order.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: baseUrl || `http://127.0.0.1:${uiPort}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
};

if (!baseUrl) {
  config.webServer = {
    command: `npx vite --config ../tests/e2e/vite.e2e.config.mjs --port ${uiPort}`,
    cwd: "./frontend",
    url: `http://127.0.0.1:${uiPort}`,
    reuseExistingServer: false,
    timeout: 120_000,
  };
}

export default config;
