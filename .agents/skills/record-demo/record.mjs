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
const showCursor = process.env.SHOW_CURSOR !== "0";
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

/**
 * Playwright records the page, not the OS pointer. This overlay is a DOM cursor
 * that follows mouse events and scales on click, so the recording shows where
 * the action happened. It is inert (pointer-events: none, aria-hidden).
 */
function installCursor() {
  const make = () => {
    if (document.getElementById("__stockroom_demo_cursor")) return;
    const cursor = document.createElement("div");
    cursor.id = "__stockroom_demo_cursor";
    cursor.setAttribute("aria-hidden", "true");
    cursor.style.cssText = [
      "position:fixed",
      "left:0",
      "top:0",
      "width:20px",
      "height:20px",
      "margin:0",
      "padding:0",
      "border:2px solid #ff4d00",
      "border-radius:50%",
      "background:rgba(255,77,0,0.18)",
      "box-shadow:0 0 0 1px rgba(255,255,255,0.9),0 2px 8px rgba(0,0,0,0.25)",
      "pointer-events:none",
      "z-index:2147483647",
      "transform:translate(-50%,-50%) scale(1)",
      "transition:left 70ms linear,top 70ms linear,transform 90ms ease",
    ].join(";");
    document.documentElement.appendChild(cursor);
    document.addEventListener(
      "mousemove",
      (event) => {
        cursor.style.left = `${event.clientX}px`;
        cursor.style.top = `${event.clientY}px`;
      },
      { passive: true },
    );
    document.addEventListener(
      "mousedown",
      () => {
        cursor.style.transform = "translate(-50%,-50%) scale(1.6)";
      },
      true,
    );
    document.addEventListener(
      "mouseup",
      () => {
        cursor.style.transform = "translate(-50%,-50%) scale(1)";
      },
      true,
    );
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", make, { once: true });
  } else {
    make();
  }
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
  if (showCursor) {
    await context.addInitScript(installCursor);
  }
  const page = await context.newPage();
  const video = page.video();

  const moveTo = async (locator, steps = 12) => {
    if (!showCursor) return;
    const box = await locator.boundingBox();
    if (!box) return;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
      steps,
    });
    await sleep(140);
  };
  const clickLocator = async (locator) => {
    await moveTo(locator);
    await locator.click();
  };
  const fillLocator = async (locator, value) => {
    await moveTo(locator, 8);
    await locator.fill(value);
  };

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    await page.getByRole("list", { name: "Stock on hand" }).waitFor();
    if (showCursor) {
      await page.mouse.move(width * 0.5, height * 0.4, { steps: 20 });
    }
    await sleep(1500);

    await clickLocator(
      page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("button", { name: "Place order" }),
    );
    await page
      .getByRole("list", { name: "Stock available to order" })
      .waitFor();
    await sleep(800);

    await clickLocator(page.getByRole("button", { name: `Add ${sku}` }));
    await fillLocator(
      page.getByLabel(`Quantity for ${sku}`),
      String(shortQty),
    );
    await fillLocator(page.getByLabel("Customer reference"), customerRef);
    await sleep(600);
    await clickLocator(
      page.getByRole("button", { name: /Reserve stock/ }),
    );
    await page.getByRole("list", { name: "Short order lines" }).waitFor();
    await sleep(2000);

    await fillLocator(page.getByLabel(`Quantity for ${sku}`), String(okQty));
    await sleep(500);
    await clickLocator(
      page.getByRole("button", { name: /Reserve stock/ }),
    );
    await page
      .getByRole("status")
      .filter({ hasText: /confirmed for/ })
      .waitFor();
    await sleep(2000);

    await clickLocator(
      page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("button", { name: "Orders" }),
    );
    await page.getByRole("list", { name: "Orders" }).waitFor();
    await sleep(800);
    await clickLocator(
      page
        .getByRole("list", { name: "Orders" })
        .getByRole("button", { name: new RegExp(customerRef) })
        .first(),
    );
    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    await sleep(1200);
    await clickLocator(dialog.getByRole("button", { name: "Fulfil order" }));
    await dialog
      .getByText(/^fulfilled$/i)
      .first()
      .waitFor();
    await sleep(600);
    await dialog
      .getByRole("heading", { name: "Movement timeline" })
      .scrollIntoViewIfNeeded();
    await sleep(2000);
    await clickLocator(dialog.getByRole("button", { name: "Close order" }));
    await dialog.waitFor({ state: "hidden" });

    await clickLocator(
      page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("button", { name: "Inventory" }),
    );
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
