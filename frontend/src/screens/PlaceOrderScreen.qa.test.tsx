import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createMockApi } from "../api";
import { renderWithApi } from "../test/render";
import PlaceOrderScreen from "./PlaceOrderScreen";

type User = ReturnType<typeof userEvent.setup>;

function submitButton(): HTMLElement {
  return screen.getByRole("button", { name: "Reserve stock" });
}

async function addLine(user: User, sku: string): Promise<void> {
  await user.click(await screen.findByRole("button", { name: `Add ${sku}` }));
}

/** Acceptance-criteria checks added by QA where the issue's proof was thin. */
describe("place order — QA acceptance checks", () => {
  it("blocks a negative quantity before submit with an inline message and aria-invalid", async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const createOrder = vi.spyOn(api, "createOrder");
    renderWithApi(<PlaceOrderScreen />, api);

    await addLine(user, "SKU-5127");
    const quantity = screen.getByLabelText("Quantity for SKU-5127");
    // `user.type` drops the minus sign on a number input, so set it directly.
    fireEvent.change(quantity, { target: { value: "-1" } });
    expect(quantity).toHaveValue(-1);

    await user.type(screen.getByLabelText("Customer reference"), "CUST-123");

    expect(
      screen.getByText(/whole number greater than zero/i),
    ).toBeInTheDocument();
    expect(quantity).toHaveAttribute("aria-invalid", "true");
    expect(submitButton()).toBeDisabled();
    expect(createOrder).not.toHaveBeenCalled();
  });

  it("applies the 3–40 character reference rule to the trimmed value", async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const createOrder = vi.spyOn(api, "createOrder");
    renderWithApi(<PlaceOrderScreen />, api);

    await addLine(user, "SKU-1042");
    const reference = screen.getByLabelText("Customer reference");

    // Six characters raw, two once trimmed: too short.
    await user.type(reference, "  ab  ");
    expect(
      screen.getByText(/between 3 and 40 characters/i),
    ).toBeInTheDocument();
    expect(reference).toHaveAttribute("aria-invalid", "true");
    expect(submitButton()).toBeDisabled();
    expect(createOrder).not.toHaveBeenCalled();

    // Forty-two characters raw, forty once trimmed: accepted, sent trimmed.
    await user.clear(reference);
    await user.type(reference, `  ${"x".repeat(40)}  `);
    expect(
      screen.queryByText(/between 3 and 40 characters/i),
    ).not.toBeInTheDocument();
    expect(reference).not.toHaveAttribute("aria-invalid");
    expect(submitButton()).not.toBeDisabled();

    await user.click(submitButton());
    expect(createOrder).toHaveBeenCalledWith({
      customer_ref: "x".repeat(40),
      lines: [{ sku: "SKU-1042", qty: 1 }],
    });
  });

  it("names only the short entries from errors[] and keeps the available line", async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<PlaceOrderScreen />, api);

    await addLine(user, "SKU-1042");
    await addLine(user, "SKU-5127");
    const quantity = screen.getByLabelText("Quantity for SKU-5127");
    await user.clear(quantity);
    await user.type(quantity, "6");
    await user.type(screen.getByLabelText("Customer reference"), "CUST-123");

    await user.click(submitButton());

    const shortLines = await screen.findByRole("list", {
      name: "Short order lines",
    });
    expect(within(shortLines).getByText(/SKU-5127/)).toBeInTheDocument();
    expect(within(shortLines).queryByText(/SKU-1042/)).not.toBeInTheDocument();
    expect(
      within(shortLines).getByText(
        "SKU-5127 requested 6 · available 5 · short by 1",
      ),
    ).toBeInTheDocument();

    expect(screen.getByLabelText("Quantity for SKU-1042")).toHaveValue(1);
    expect(screen.getByLabelText("Customer reference")).toHaveValue("CUST-123");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
