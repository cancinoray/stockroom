---
name: record-demo
description: Record a silent, browser-only walkthrough of the Stockroom app with Playwright — inventory, a short-line 409, a successful reservation, and fulfilment. Use for demo-video retakes or visual evidence; it does not capture the terminal, Grafana, the host deploy or voice.
---

# Record the app demo

Use this when you need a repeatable, silent screen recording of the **browser-only** app flow. The
full three-minute submission video is still human work: follow
[`_docs/demo-script.md`](../../../_docs/demo-script.md) and capture the terminal, Grafana, alert and
deployment beats separately.

## What it records

1. Inventory with the seeded low-stock badges.
2. Place order: an order one unit over availability → per-line `409`, then the corrected quantity →
   `201`.
3. Orders: open the new order’s drawer, fulfil it, show the movement timeline.
4. Inventory again, after the stock has moved.

Output is a `.webm` plus an H.264 `.mp4` if `ffmpeg` is installed. It is silent by design.

## Prerequisites

- Node 20+ and the frontend dependencies: `cd frontend && npm ci`
- Playwright’s Chromium: `cd frontend && npx playwright install chromium`
- A running, migrated, **seeded** stack. From the repo root:
  ```sh
  make dev
  ```
  If port 8000 is busy, use the local override from the README and pass the remapped origin.
- For a repeatable run, reset to seed data first:
  ```sh
  docker compose down -v
  make dev
  ```
  This wipes the local database and reseeds one `MAIN` warehouse and eight products.

## Run it

From the repo root:

```sh
STOCKROOM_URL=http://localhost:8000 \
OUT_DIR=/tmp/stockroom-demo \
node .agents/skills/record-demo/record.mjs
```

With the 18000 port override:

```sh
STOCKROOM_URL=http://localhost:18000 \
OUT_DIR=/tmp/stockroom-demo \
node .agents/skills/record-demo/record.mjs
```

Useful environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `STOCKROOM_URL` | `http://localhost:8000` | App origin; `/healthz` and `/api/stock` must answer there |
| `OUT_DIR` | `/tmp/stockroom-demo` | Where the recording is written; do not commit it |
| `DEMO_SKU` | `SKU-8820` | SKU used for the 409 → 201 story; it must have stock |
| `DEMO_CUSTOMER_REF` | `CUST-DEMO` | Allowed synthetic customer reference |
| `STOCKROOM_FRONTEND` | `../../../frontend` | Directory containing `node_modules` and `package.json`; set this when running from a worktree without its own install |

The script reads availability from `/api/stock`, requests one more unit than available, asserts the
short-line list appears, then requests the available quantity and waits for the confirmation. It then
opens the order drawer, fulfils it, and ends on Inventory.

## Outputs

```
$OUT_DIR/stockroom-app-demo.webm
$OUT_DIR/stockroom-app-demo.mp4   # if ffmpeg is available
$OUT_DIR/raw/                     # Playwright’s intermediate video
```

Do **not** commit the recording. `OUT_DIR` defaults to `/tmp` for that reason. The recording is
silent; add narration in the editor or record the full screen with QuickTime/`ffmpeg` for the
submission video.

## Troubleshooting

- **`/healthz` unreachable or `db` not `ok`** — the stack is down or migrations/seed have not run.
  Use `make dev`; check `curl "$STOCKROOM_URL/healthz"`.
- **`SKU-8820 has N available`** — a previous run consumed it. Reset:
  `docker compose down -v && make dev`, or set `DEMO_SKU` to another seeded SKU with stock.
- **`Cannot find module '@playwright/test'`** — run `cd frontend && npm ci`; if running the skill from
  another worktree, set `STOCKROOM_FRONTEND` to the frontend directory that has `node_modules`.
- **`Executable doesn't exist`** — `cd frontend && npx playwright install chromium`.
- **Port 8000 is taken** — use the `compose.override.yaml` recipe in the README and set
  `STOCKROOM_URL=http://localhost:<port>`.
- **Blank/black video** — ensure Chromium is installed and the app is reachable; the script uses
  headless Chromium, which does not need a display.

## Guardrails

- Seeded demo data only. Use `CUST-DEMO`; never put a real customer name, email, token or DSN on screen.
- Do not modify product code or the app’s seeded data to make a shot work; reset instead.
- This skill is not a substitute for the human submission video: it has no terminal, Grafana, deploy
  or narration, and it does not submit anything.
