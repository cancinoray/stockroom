#!/usr/bin/env node
/**
 * Record a silent, browser-only walkthrough of the Stockroom app.
 *
 * It is intentionally not a full demo-video recorder: it has no terminal, Grafana, deploy or voice.
 * Use _docs/demo-script.md for the full submission video and this skill for app-flow retakes.
 */

import { execFile } from "node:child_process";
import { mkdir, rename, stat } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const frontendDir =
  process.env.STOCKROOM_FRONTEND ?? path.resolve(here, "../../../frontend");
const require = createRequire(path.join(frontendDir, "package.json"));
const { chromium } = require("@playwright/test");

const baseUrl = (process.env.STOCKROOM_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);
const outDir = path.resolve(process.env.OUT_DIR ?? "/tmp/stockroom-demo");
const rawDir = path.join(outDir, "raw");
const sku = process.env.DEMO_SKU ?? "SKU-8820";
const customerRef = process.env.DEMO_CUSTOMER_REF ?? "CUST-DEMO";
const width = 1440;
const height = 900;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.json();
}

async function main() {
  await mkdir(rawDir, { recursive: true });

  const health = await getJson(`${baseUrl}/healthz`).catch((error) => {
    throw new Error(
      `Cannot reach ${baseUrl}/healthz (${error.message}). Is the stack running? Try: make dev`,
    );
  });
  if (health.db !== "ok") {
    throw new Error(
      `/healthz reports db=${health.db}. Start a migrated, seeded stack: make dev`,
    );
  }

  const stock = await getJson(`${baseUrl}/api/stock`);
  const row = stock.find((candidate) => candidate.sku === sku);
  if (!row) {
    throw new Error(
      `${sku} is not in /api/stock. Reset the stack: docker compose down -v && make dev`,
    );
  }
  if (row.available < 1) {
    throw new Error(
      `${sku} has ${row.available} available. Reset the stack: docker compose down -v && make dev`,
    );
  }
  const shortQty = row.available + 1;
  const okQty = row.available;
  console.log(
    `Recording ${baseUrl} · ${sku} available=${row.available} (show ${shortQty}, then ${okQty})`,
  );

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width, height },
    recordVideo: { dir: rawDir, size: { width, height } },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const video = page.video();

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    await page.getByRole("list", { name: "Stock on hand" }).waitFor();
    await sleep(1500);

    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Place order" })
      .click();
    await page
      .getByRole("list", { name: "Stock available to order" })
      .waitFor();
    await sleep(800);

    await page.getByRole("button", { name: `Add ${sku}` }).click();
    await page.getByLabel(`Quantity for ${sku}`).fill(String(shortQty));
    await page.getByLabel("Customer reference").fill(customerRef);
    await sleep(600);
    await page.getByRole("button", { name: /Reserve stock/ }).click();
    await page.getByRole("list", { name: "Short order lines" }).waitFor();
    await sleep(2000);

    await page.getByLabel(`Quantity for ${sku}`).fill(String(okQty));
    await sleep(500);
    await page.getByRole("button", { name: /Reserve stock/ }).click();
    await page
      .getByRole("status")
      .filter({ hasText: /confirmed for/ })
      .waitFor();
    await sleep(2000);

    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Orders" })
      .click();
    await page.getByRole("list", { name: "Orders" }).waitFor();
    await sleep(800);
    await page
      .getByRole("list", { name: "Orders" })
      .getByRole("button", { name: new RegExp(customerRef) })
      .first()
      .click();
    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    await sleep(1200);
    await dialog.getByRole("button", { name: "Fulfil order" }).click();
    await dialog
      .getByText(/^fulfilled$/i)
      .first()
      .waitFor();
    await sleep(600);
    await dialog
      .getByRole("heading", { name: "Movement timeline" })
      .scrollIntoViewIfNeeded();
    await sleep(2000);
    await dialog.getByRole("button", { name: "Close order" }).click();
    await dialog.waitFor({ state: "hidden" });

    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Inventory" })
      .click();
    await page.getByRole("list", { name: "Stock on hand" }).waitFor();
    await sleep(1500);
  } finally {
    await context.close();
    await browser.close();
  }

  const rawPath = await video.path();
  const webm = path.join(outDir, "stockroom-app-demo.webm");
  await rename(rawPath, webm);
  console.log(`webm: ${webm}`);

  const mp4 = path.join(outDir, "stockroom-app-demo.mp4");
  try {
    await execFileAsync(
      "ffmpeg",
      ["-y", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", mp4],
      { maxBuffer: 64 * 1024 * 1024 },
    );
    const info = await stat(mp4);
    console.log(`mp4:  ${mp4} (${Math.round(info.size / 1024)} KiB)`);
  } catch (error) {
    console.warn(
      `ffmpeg unavailable or failed; keeping the webm (${error.message})`,
    );
  }

  console.log(
    "Silent browser-only recording. Add narration and the terminal/Grafana beats separately.",
  );
}

main().catch((error) => {
  console.error(`\n${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
