import { expect, test } from "@playwright/test";

import { chartRow, shelfRow } from "./support";

/**
 * US6-AC1 (e2e): the seed opens SKU-5127 at 6 on hand against a reorder point
 * of 10, so the table marks it LOW; a receive through the UI dialog takes it
 * one past the point and clears the badge.
 */
test("marks a seeded SKU LOW and clears the badge after a receive through the dialog", async ({
  page,
}) => {
  await page.goto("/");

  const ticket = shelfRow(page, "SKU-5127");
  await expect(ticket).toBeVisible();
  await expect(ticket.getByText("Low", { exact: true })).toBeVisible();
  await expect(chartRow(page, "SKU-5127")).toContainText(
    "6 on hand · 0 reserved · 6 available",
  );

  await page.getByRole("button", { name: "Receive SKU-5127" }).click();
  const dialog = page.getByRole("dialog", { name: "Receive stock" });
  await expect(dialog).toBeVisible();

  await dialog.getByLabel("Quantity received").fill("5");
  await dialog.getByLabel("Note (optional)").fill("E2E delivery");
  await dialog.getByRole("button", { name: "Receive stock" }).click();
  await expect(dialog).toBeHidden();

  await expect(ticket.getByText("Low", { exact: true })).toHaveCount(0);
  await expect(chartRow(page, "SKU-5127")).toContainText(
    "11 on hand · 0 reserved · 11 available",
  );
});

/**
 * US6-AC4 (e2e): the history drawer shows the opening movement's reason, note,
 * actor and running balance, and the inventory page is still the page behind
 * the overlay.
 */
test("opens a SKU ledger with reason, actor, note and running balance without leaving the page", async ({
  page,
}) => {
  await page.goto("/");
  await expect(shelfRow(page, "SKU-1042")).toBeVisible();

  await page
    .getByRole("button", { name: "Movement history for SKU-1042" })
    .click();
  const drawer = page.getByRole("dialog", { name: "Why this count?" });
  await expect(drawer).toBeVisible();

  const opening = drawer
    .getByRole("list", { name: "Movement ledger" })
    .getByRole("listitem")
    .filter({ hasText: "Opening count" });

  await expect(opening).toContainText("receive");
  await expect(opening).toContainText("Opening count");
  await expect(opening).toContainText("demo-operator");
  await expect(opening).toContainText(/On hand \+18/);
  await expect(opening).toContainText(/Balance 18/);

  await expect(page.getByRole("heading", { name: "Inventory" })).toBeVisible();
  await expect(shelfRow(page, "SKU-1042")).toBeVisible();

  await drawer.getByRole("button", { name: "Close ledger" }).click();
  await expect(drawer).toBeHidden();
});
