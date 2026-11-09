import { expect, type Page } from "@playwright/test";

/**
 * Locators shared by the specs. Everything here is role- or label-based: the
 * screens expose named lists, dialogs and buttons, so no CSS class and no
 * `data-testid` is needed.
 */

export function screenNav(page: Page) {
  return page.getByRole("navigation", { name: "Main navigation" });
}

export async function openScreen(page: Page, name: string) {
  await screenNav(page).getByRole("button", { name }).click();
}

/** One bin ticket in the inventory list. */
export function shelfRow(page: Page, sku: string) {
  return page
    .getByRole("list", { name: "Stock on hand" })
    .getByRole("listitem")
    .filter({ hasText: sku });
}

/** One row of the stock position chart, which repeats the counters as text. */
export function chartRow(page: Page, sku: string) {
  return page
    .getByRole("region", { name: "Stock on hand" })
    .getByRole("listitem")
    .filter({ hasText: sku });
}

export function ordersList(page: Page) {
  return page.getByRole("list", { name: "Orders" });
}

/** Wait for the orders screen to finish its first read before counting rows. */
export async function ordersLoaded(page: Page) {
  await expect(ordersList(page)).toBeVisible();
  await expect(page.getByText("Reading orders…")).toHaveCount(0);
}
