import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import {
  ApiProblem,
  createMockApi,
  type Problem,
  type StockroomApi,
} from '../api';
import { renderWithApi } from '../test/render';
import PlaceOrderScreen from './PlaceOrderScreen';

type User = ReturnType<typeof userEvent.setup>;

const SHELF = 'Stock available to order';

function shelf(): HTMLElement {
  return screen.getByRole('list', { name: SHELF });
}

function shelfRow(sku: string): HTMLElement {
  const row = within(shelf()).getByText(sku).closest('li');
  if (!(row instanceof HTMLElement)) {
    throw new Error(`No shelf row for ${sku}`);
  }
  return row;
}

function submitButton(): HTMLElement {
  return screen.getByRole('button', { name: 'Reserve stock' });
}

async function addLine(user: User, sku: string): Promise<void> {
  await user.click(await screen.findByRole('button', { name: `Add ${sku}` }));
}

async function setQuantity(
  user: User,
  sku: string,
  value: string,
): Promise<void> {
  const input = screen.getByLabelText(`Quantity for ${sku}`);
  await user.clear(input);
  await user.type(input, value);
}

function failingCreateOrder(problem: Problem): StockroomApi {
  const api = createMockApi({ latencyMs: 0 });
  vi.spyOn(api, 'createOrder').mockRejectedValue(new ApiProblem(problem));
  return api;
}

describe('place order', () => {
  it('filters the picker by SKU or name and shows each result’s available', async () => {
    const user = userEvent.setup();
    renderWithApi(<PlaceOrderScreen />, createMockApi({ latencyMs: 0 }));

    const search = await screen.findByLabelText('Search stock');
    await screen.findByRole('list', { name: SHELF });

    await user.type(search, 'cable');
    expect(within(shelf()).getByText('SKU-5127')).toBeInTheDocument();
    expect(within(shelf()).queryByText('SKU-1042')).not.toBeInTheDocument();
    expect(within(shelfRow('SKU-5127')).getByText('5')).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, 'desk lamp');
    expect(within(shelf()).getByText('SKU-1042')).toBeInTheDocument();
    expect(within(shelf()).queryByText('SKU-5127')).not.toBeInTheDocument();
    expect(within(shelfRow('SKU-1042')).getByText('15')).toBeInTheDocument();
  });

  it('shows an empty state, not an error, when the search has no match', async () => {
    const user = userEvent.setup();
    renderWithApi(<PlaceOrderScreen />, createMockApi({ latencyMs: 0 }));

    const search = await screen.findByLabelText('Search stock');
    await screen.findByRole('list', { name: SHELF });

    await user.type(search, 'no-such-thing');

    expect(screen.getByText('No match')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: SHELF })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows one mono loading line while stock loads', async () => {
    renderWithApi(<PlaceOrderScreen />, createMockApi({ latencyMs: 40 }));

    expect(screen.getAllByText('Reading the shelf…')).toHaveLength(1);
    expect(screen.queryByText('No match')).not.toBeInTheDocument();

    await screen.findByRole('list', { name: SHELF });
    expect(screen.queryByText('Reading the shelf…')).not.toBeInTheDocument();
  });

  it('keeps the form usable when stock cannot be read', async () => {
    const api = createMockApi({ latencyMs: 0 });
    vi.spyOn(api, 'listStock').mockRejectedValue(
      new ApiProblem({
        type: 'service_unavailable',
        title: 'Stock unavailable',
        status: 503,
        detail: 'The stock service is not responding.',
        trace_id: 'trace-stock-1',
      }),
    );
    renderWithApi(<PlaceOrderScreen />, api);

    expect(await screen.findByText('Could not read stock')).toBeInTheDocument();
    expect(
      screen.getByText('The stock service is not responding.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/trace-stock-1/)).toBeInTheDocument();
    expect(screen.getByLabelText('Customer reference')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Reserve stock' }),
    ).toBeInTheDocument();
  });

  it('adds the same SKU once, incrementing its quantity, and sends the trimmed reference', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const createOrder = vi.spyOn(api, 'createOrder');
    renderWithApi(<PlaceOrderScreen />, api);

    await addLine(user, 'SKU-1042');
    await addLine(user, 'SKU-1042');
    await addLine(user, 'SKU-3301');

    const orderLines = screen.getByRole('list', { name: 'Order lines' });
    expect(within(orderLines).getAllByText('SKU-1042')).toHaveLength(1);
    expect(screen.getByLabelText('Quantity for SKU-1042')).toHaveValue(2);

    await user.type(screen.getByLabelText('Customer reference'), '  CUST-77  ');
    await user.click(submitButton());

    expect(createOrder).toHaveBeenCalledWith({
      customer_ref: 'CUST-77',
      lines: [
        { sku: 'SKU-1042', qty: 2 },
        { sku: 'SKU-3301', qty: 1 },
      ],
    });
  });

  it('enforces the customer reference rule after trimming before submit', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const createOrder = vi.spyOn(api, 'createOrder');
    renderWithApi(<PlaceOrderScreen />, api);

    const reference = await screen.findByLabelText('Customer reference');
    await addLine(user, 'SKU-1042');

    await user.type(reference, 'ab');
    expect(
      screen.getByText(/between 3 and 40 characters/i),
    ).toBeInTheDocument();
    expect(reference).toHaveAttribute('aria-invalid', 'true');
    expect(submitButton()).toBeDisabled();
    expect(createOrder).not.toHaveBeenCalled();

    await user.clear(reference);
    await user.type(reference, 'x'.repeat(41));
    expect(
      screen.getByText(/between 3 and 40 characters/i),
    ).toBeInTheDocument();
    expect(reference).toHaveAttribute('aria-invalid', 'true');
    expect(submitButton()).toBeDisabled();
    expect(createOrder).not.toHaveBeenCalled();

    await user.clear(reference);
    await user.type(reference, '  CUST-77  ');
    expect(
      screen.queryByText(/between 3 and 40 characters/i),
    ).not.toBeInTheDocument();
    expect(reference).not.toHaveAttribute('aria-invalid');
    await user.click(submitButton());
    expect(createOrder).toHaveBeenCalledWith({
      customer_ref: 'CUST-77',
      lines: [{ sku: 'SKU-1042', qty: 1 }],
    });
  });

  it('shows 201 confirmed with the order id and refetches the reduced availability', async () => {
    const user = userEvent.setup();
    renderWithApi(<PlaceOrderScreen />, createMockApi({ latencyMs: 30 }));

    await addLine(user, 'SKU-1042');
    await setQuantity(user, 'SKU-1042', '2');
    await user.type(screen.getByLabelText('Customer reference'), 'CUST-900');

    expect(within(shelfRow('SKU-1042')).getByText('15')).toBeInTheDocument();

    await user.click(submitButton());

    // The shelf is never decremented locally: it still shows the pre-order count.
    expect(within(shelfRow('SKU-1042')).getByText('15')).toBeInTheDocument();

    const status = await screen.findByRole('status');
    expect(within(status).getByText('201')).toBeInTheDocument();
    expect(within(status).getByText('confirmed')).toBeInTheDocument();
    expect(within(status).getByText(/ord-1006/)).toBeInTheDocument();

    await waitFor(() =>
      expect(within(shelfRow('SKU-1042')).getByText('13')).toBeInTheDocument(),
    );

    expect(screen.getByLabelText('Customer reference')).toHaveValue('');
    expect(
      screen.queryByRole('list', { name: 'Order lines' }),
    ).not.toBeInTheDocument();
  });

  it('labels the pending control Reserving… and keeps the ticket until the response', async () => {
    const user = userEvent.setup();
    renderWithApi(<PlaceOrderScreen />, createMockApi({ latencyMs: 40 }));

    await addLine(user, 'SKU-1042');
    await user.type(screen.getByLabelText('Customer reference'), 'CUST-900');
    await user.click(submitButton());

    const pending = screen.getByRole('button', { name: 'Reserving…' });
    expect(pending).toBeDisabled();
    expect(screen.getByLabelText('Quantity for SKU-1042')).toBeInTheDocument();
    expect(screen.getByLabelText('Customer reference')).toHaveValue('CUST-900');

    expect(await screen.findByRole('status')).toBeInTheDocument();
  });

  it('names the short line and does not create the order', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<PlaceOrderScreen />, api);

    await addLine(user, 'SKU-5127');
    await setQuantity(user, 'SKU-5127', '6');

    await user.type(screen.getByLabelText('Customer reference'), 'CUST-123');
    await user.click(submitButton());

    expect(await screen.findByText(/short by 1/i)).toBeInTheDocument();
    expect(await api.listOrders()).toHaveLength(5);
  });

  it('renders every short line with requested, available and short-by, keeping the ticket', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const listStock = vi.spyOn(api, 'listStock');
    renderWithApi(<PlaceOrderScreen />, api);

    await addLine(user, 'SKU-5127');
    await setQuantity(user, 'SKU-5127', '6');
    await addLine(user, 'SKU-8820');
    await setQuantity(user, 'SKU-8820', '3');
    await user.type(screen.getByLabelText('Customer reference'), 'CUST-123');
    await user.click(submitButton());

    expect(
      await screen.findByText(
        'SKU-5127 requested 6 · available 5 · short by 1',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText('SKU-8820 requested 3 · available 2 · short by 1'),
    ).toBeInTheDocument();

    expect(screen.getByLabelText('Customer reference')).toHaveValue('CUST-123');
    expect(screen.getByLabelText('Quantity for SKU-5127')).toHaveValue(6);
    expect(screen.getByLabelText('Quantity for SKU-8820')).toHaveValue(3);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    await waitFor(() =>
      expect(listStock.mock.calls.length).toBeGreaterThanOrEqual(2),
    );
  });

  it('keeps focus and announces the error when a short line fails the submit', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<PlaceOrderScreen />, api);

    await addLine(user, 'SKU-5127');
    await setQuantity(user, 'SKU-5127', '6');
    await user.type(screen.getByLabelText('Customer reference'), 'CUST-123');

    const submit = submitButton();
    await user.click(submit);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/short/i);
    expect(submit).toHaveFocus();
  });

  it('renders a 422 unknown-SKU problem envelope with type, title, detail and trace id', async () => {
    const user = userEvent.setup();
    renderWithApi(
      <PlaceOrderScreen />,
      failingCreateOrder({
        type: 'validation_error',
        title: 'Unknown SKU',
        status: 422,
        detail: 'The order names a SKU that does not exist.',
        trace_id: 'trace-sku-1',
        errors: [{ field: 'lines.0.sku', message: 'SKU-9999 does not exist.' }],
      }),
    );

    await addLine(user, 'SKU-1042');
    await user.type(screen.getByLabelText('Customer reference'), 'CUST-123');
    await user.click(submitButton());

    expect(await screen.findByText(/validation_error/)).toBeInTheDocument();
    expect(screen.getByText('Unknown SKU')).toBeInTheDocument();
    expect(
      screen.getByText('The order names a SKU that does not exist.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/trace-sku-1/)).toBeInTheDocument();
    expect(screen.getByText(/lines\.0\.sku/)).toBeInTheDocument();
    expect(screen.getByText(/SKU-9999 does not exist\./)).toBeInTheDocument();

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Customer reference')).toHaveValue('CUST-123');
    expect(screen.getByLabelText('Quantity for SKU-1042')).toBeInTheDocument();
  });

  it('renders a 422 for an invalid quantity as a problem envelope, not an unhandled error', async () => {
    const user = userEvent.setup();
    renderWithApi(
      <PlaceOrderScreen />,
      failingCreateOrder({
        type: 'validation_error',
        title: 'Invalid quantity',
        status: 422,
        detail: 'Quantity must be a whole number greater than zero.',
        trace_id: 'trace-qty-1',
        errors: [
          {
            field: 'lines.0.qty',
            message: 'Input should be a valid integer',
            value: 'many',
          },
        ],
      }),
    );

    await addLine(user, 'SKU-1042');
    await user.type(screen.getByLabelText('Customer reference'), 'CUST-123');
    await user.click(submitButton());

    expect(await screen.findByText('Invalid quantity')).toBeInTheDocument();
    expect(
      screen.getByText('Quantity must be a whole number greater than zero.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/trace-qty-1/)).toBeInTheDocument();
    expect(screen.getByText(/lines\.0\.qty/)).toBeInTheDocument();
    expect(
      screen.getByText(/Input should be a valid integer/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('blocks a zero quantity before calling the API', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const createOrder = vi.spyOn(api, 'createOrder');
    renderWithApi(<PlaceOrderScreen />, api);

    await addLine(user, 'SKU-5127');

    const quantity = screen.getByLabelText('Quantity for SKU-5127');
    await user.clear(quantity);
    await user.type(quantity, '0');
    await user.type(screen.getByLabelText('Customer reference'), 'CUST-123');

    expect(
      screen.getByText(/whole number greater than zero/i),
    ).toBeInTheDocument();
    expect(quantity).toHaveAttribute('aria-invalid', 'true');
    expect(
      screen.getByRole('button', { name: 'Reserve stock' }),
    ).toBeDisabled();
    expect(createOrder).not.toHaveBeenCalled();
  });

  it('labels the search, the customer reference and every quantity input', async () => {
    const user = userEvent.setup();
    renderWithApi(<PlaceOrderScreen />, createMockApi({ latencyMs: 0 }));

    await addLine(user, 'SKU-1042');

    expect(screen.getByLabelText('Search stock')).toBeInTheDocument();
    expect(screen.getByLabelText('Customer reference')).toBeInTheDocument();
    expect(screen.getByLabelText('Quantity for SKU-1042')).toBeInTheDocument();
  });
});
