import { expect, test } from "@playwright/test";

import {
  chartRow,
  openBay,
  ordersList,
  ordersLoaded,
  shelfRow,
} from "./support";

/**
 * US1-AC1 failure path (e2e): one short line rejects the whole order. The
 * problem title and the named short line render, no order row is added, and
 * neither SKU's available count moves — including the line that could have
 * been reserved on its own.
 */
test("a short line rejects the whole order and reserves nothing", async ({
  page,
}) => {
  await page.goto("/");
  await expect(shelfRow(page, "SKU-4410")).toBeVisible();
  await expect(chartRow(page, "SKU-4410")).toContainText(
    "5 on hand · 0 reserved · 5 available",
  );
  await expect(chartRow(page, "SKU-2087")).toContainText(
    "10 on hand · 0 reserved · 10 available",
  );

  await openBay(page, "Orders");
  await ordersLoaded(page);
  const orders = ordersList(page).getByRole("listitem");
  const ordersBefore = await orders.count();

  await openBay(page, "Place order");
  const search = page.getByRole("searchbox", { name: "Search stock" });

  await search.fill("SKU-4410");
  await page.getByRole("button", { name: "Add SKU-4410" }).click();
  await search.fill("SKU-2087");
  await page.getByRole("button", { name: "Add SKU-2087" }).click();

  await page.getByLabel("Quantity for SKU-4410").fill("1");
  await page.getByLabel("Quantity for SKU-2087").fill("11");
  await page.getByLabel("Customer reference").fill("E2E-SHORT-1");
  await page.getByRole("button", { name: "Reserve stock" }).click();

  const problem = page.getByRole("alert");
  await expect(problem).toContainText("Not enough stock");
  await expect(problem).toContainText(
    "SKU-2087 is short. No stock was reserved.",
  );

  const shortLines = page.getByRole("list", { name: "Short order lines" });
  await expect(shortLines.getByRole("listitem")).toHaveCount(1);
  await expect(shortLines).toContainText("SKU-2087");
  await expect(shortLines).toContainText("short by 1");

  await expect(page.getByRole("status")).toHaveCount(0);

  await openBay(page, "Inventory");
  await expect(chartRow(page, "SKU-4410")).toContainText(
    "5 on hand · 0 reserved · 5 available",
  );
  await expect(chartRow(page, "SKU-2087")).toContainText(
    "10 on hand · 0 reserved · 10 available",
  );

  await openBay(page, "Orders");
  await ordersLoaded(page);
  await expect(orders).toHaveCount(ordersBefore);
});
