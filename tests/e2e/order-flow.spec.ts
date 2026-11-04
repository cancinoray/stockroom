import { expect, test } from "@playwright/test";

import { chartRow, openBay, ordersList, shelfRow } from "./support";

/**
 * US1-AC1 + US4-AC1 (e2e): search a SKU, add it, set quantity and customer
 * reference, reserve (201), then fulfil the order from the Orders lane. The
 * inventory counters show the reservation and then the ship.
 */
test("searches, reserves and fulfils an order, and the counters reflect the ship", async ({
  page,
}) => {
  await page.goto("/");
  await expect(shelfRow(page, "SKU-3301")).toBeVisible();
  await expect(chartRow(page, "SKU-3301")).toContainText(
    "40 on hand · 0 reserved · 40 available",
  );

  await openBay(page, "Place order");
  await page.getByRole("searchbox", { name: "Search stock" }).fill("SKU-3301");
  await expect(
    page
      .getByRole("list", { name: "Stock available to order" })
      .getByRole("listitem"),
  ).toHaveCount(1);

  await page.getByRole("button", { name: "Add SKU-3301" }).click();
  await page.getByLabel("Quantity for SKU-3301").fill("2");
  await page.getByLabel("Customer reference").fill("E2E-FLOW-1");
  await page.getByRole("button", { name: "Reserve stock" }).click();

  const confirmation = page.getByRole("status");
  await expect(confirmation).toContainText("E2E-FLOW-1");
  await expect(confirmation).toContainText("201");
  await expect(confirmation).toContainText("confirmed");

  await openBay(page, "Inventory");
  await expect(chartRow(page, "SKU-3301")).toContainText(
    "40 on hand · 2 reserved · 38 available",
  );

  await openBay(page, "Orders");
  await ordersList(page)
    .getByRole("button")
    .filter({ hasText: "E2E-FLOW-1" })
    .click();

  const drawer = page.getByRole("dialog", { name: "E2E-FLOW-1" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("confirmed", { exact: true })).toBeVisible();

  await drawer.getByRole("button", { name: "Fulfil order" }).click();
  await expect(drawer.getByText("fulfilled", { exact: true })).toBeVisible();
  await expect(drawer.getByText("ship", { exact: true })).toBeVisible();

  await drawer.getByRole("button", { name: "Close order" }).click();
  await expect(drawer).toBeHidden();

  await openBay(page, "Inventory");
  await expect(chartRow(page, "SKU-3301")).toContainText(
    "38 on hand · 0 reserved · 38 available",
  );
});
