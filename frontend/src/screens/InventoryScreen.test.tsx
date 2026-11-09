import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiProblem, createMockApi, type Problem, type StockRow, type StockroomApi } from '../api';
import { renderWithApi } from '../test/render';
import InventoryScreen from './InventoryScreen';

function apiWith(overrides: Partial<StockroomApi>): StockroomApi {
  return { ...createMockApi({ latencyMs: 0 }), ...overrides };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function problem(overrides: Partial<Problem> = {}): Problem {
  return {
    type: 'unexpected',
    title: 'Unexpected error',
    status: 500,
    detail: 'The request failed.',
    trace_id: 'trace-default',
    ...overrides,
  };
}

async function stockList(): Promise<HTMLElement> {
  return screen.findByRole('list', { name: 'Stock on hand' });
}

async function findRow(list: HTMLElement, sku: string): Promise<HTMLElement> {
  const label = await within(list).findByText(sku);
  const row = label.closest('li');
  if (!row) {
    throw new Error(`No stock row for ${sku}`);
  }
  return row;
}

function metric(row: HTMLElement, label: string): string {
  const labelEl = within(row).getByText(label);
  return labelEl.nextElementSibling?.textContent ?? '';
}

function currentRow(list: HTMLElement, sku: string): HTMLElement {
  const label = within(list).getByText(sku);
  const row = label.closest('li');
  if (!row) {
    throw new Error(`No stock row for ${sku}`);
  }
  return row;
}

const received: StockRow = {
  sku: 'SKU-1042',
  name: 'Desk lamp, matte black',
  on_hand: 19,
  reserved: 3,
  available: 16,
  reorder_point: 6,
  unit_price_cents: 129_900,
  low: false,
};

describe('inventory', () => {
  it('marks low stock and opens the movement ledger without leaving the page', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<InventoryScreen />, api);

    const shelf = await screen.findByRole('list', { name: 'Stock on hand' });
    await within(shelf).findByText('SKU-1042');
    expect(within(shelf).getAllByText('Low')).toHaveLength(4);
    expect(within(shelf).getByText('SKU-5127')).toBeInTheDocument();

    const historyButton = screen.getByRole('button', {
      name: 'Movement history for SKU-1042',
    });
    await user.click(historyButton);

    expect(await screen.findByText(/Opening count/)).toBeInTheDocument();
    expect(screen.getByText('Why this count?')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(historyButton).toHaveFocus());
  });

  it('traps focus in the receive dialog and restores it on close', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<InventoryScreen />, api);

    const trigger = await screen.findByRole('button', {
      name: 'Receive SKU-1042',
    });
    await user.click(trigger);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveFocus();

    await user.tab({ shift: true });
    expect(within(dialog).getByRole('button', { name: 'Receive stock' })).toHaveFocus();

    await user.tab();
    expect(within(dialog).getByRole('button', { name: 'Close dialog' })).toHaveFocus();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('renders SKU, name, PHP price, every counter and the low marker from the row', async () => {
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<InventoryScreen />, api);

    const list = await stockList();
    const row = await findRow(list, 'SKU-1042');

    expect(within(row).getByText('Desk lamp, matte black')).toBeInTheDocument();
    expect(within(row).getByText('₱1,299.00 each')).toBeInTheDocument();
    expect(metric(row, 'On hand')).toBe('18');
    expect(metric(row, 'Reserved')).toBe('3');
    expect(metric(row, 'Available')).toBe('15');
    expect(metric(row, 'Reorder at')).toBe('6');
    expect(within(row).queryByText(/^low$/i)).not.toBeInTheDocument();

    const atPoint = await findRow(list, 'SKU-8820');
    expect(metric(atPoint, 'Available')).toBe('2');
    expect(metric(atPoint, 'Reorder at')).toBe('2');
    expect(within(atPoint).getByText(/^low$/i)).toBeInTheDocument();
  });

  it('renders LOW at available == reorder_point and none at reorder_point + 1', async () => {
    const listStock = async (): Promise<StockRow[]> => [
      {
        sku: 'SKU-9001',
        name: 'Boundary bracket, at the point',
        on_hand: 9,
        reserved: 2,
        available: 7,
        reorder_point: 7,
        unit_price_cents: 12_500,
        low: true,
      },
      {
        sku: 'SKU-9002',
        name: 'Boundary bracket, one above the point',
        on_hand: 10,
        reserved: 2,
        available: 8,
        reorder_point: 7,
        unit_price_cents: 12_500,
        low: false,
      },
    ];
    renderWithApi(<InventoryScreen />, apiWith({ listStock }));

    const list = await stockList();

    const atPoint = await findRow(list, 'SKU-9001');
    expect(metric(atPoint, 'On hand')).toBe('9');
    expect(metric(atPoint, 'Reserved')).toBe('2');
    expect(metric(atPoint, 'Available')).toBe('7');
    expect(within(atPoint).getByText(/^low$/i)).toBeInTheDocument();

    const oneAbove = await findRow(list, 'SKU-9002');
    expect(metric(oneAbove, 'On hand')).toBe('10');
    expect(metric(oneAbove, 'Reserved')).toBe('2');
    expect(metric(oneAbove, 'Available')).toBe('8');
    expect(within(oneAbove).queryByText(/^low$/i)).not.toBeInTheDocument();
  });

  it('clears LOW only after a receive refetches available to reorder_point + 1', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const listStock = vi.spyOn(api, 'listStock');
    renderWithApi(<InventoryScreen />, api);

    const list = await stockList();
    const before = await findRow(list, 'SKU-8820');
    expect(metric(before, 'Available')).toBe('2');
    expect(within(before).getByText(/^low$/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Receive SKU-8820' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Receive stock' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await waitFor(() => {
      const after = currentRow(list, 'SKU-8820');
      expect(metric(after, 'Available')).toBe('3');
      expect(metric(after, 'On hand')).toBe('4');
      expect(within(after).queryByText(/^low$/i)).not.toBeInTheDocument();
    });
    expect(listStock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('posts exactly one receive and shows the higher counters from the refetched list', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const receiveStock = vi.spyOn(api, 'receiveStock');
    const listStock = vi.spyOn(api, 'listStock');
    renderWithApi(<InventoryScreen />, api);

    const list = await stockList();
    const before = await findRow(list, 'SKU-5127');
    expect(metric(before, 'On hand')).toBe('6');
    expect(metric(before, 'Available')).toBe('5');

    await user.click(screen.getByRole('button', { name: 'Receive SKU-5127' }));
    const dialog = await screen.findByRole('dialog');

    const qty = within(dialog).getByLabelText('Quantity received');
    await user.clear(qty);
    await user.type(qty, '3');
    await user.type(within(dialog).getByLabelText('Note (optional)'), 'Delivery 4471');
    await user.click(within(dialog).getByRole('button', { name: 'Receive stock' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    expect(receiveStock).toHaveBeenCalledTimes(1);
    expect(receiveStock.mock.calls[0][0]).toEqual({
      sku: 'SKU-5127',
      qty: 3,
      note: 'Delivery 4471',
    });

    await waitFor(() => {
      const after = currentRow(list, 'SKU-5127');
      expect(metric(after, 'On hand')).toBe('9');
      expect(metric(after, 'Available')).toBe('8');
    });
    expect(listStock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('blocks blank, zero, negative and fractional receive quantities before submit', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const receiveStock = vi.spyOn(api, 'receiveStock');
    renderWithApi(<InventoryScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Receive SKU-1042' }));
    const dialog = await screen.findByRole('dialog');
    const qty = within(dialog).getByLabelText('Quantity received');
    const submit = within(dialog).getByRole('button', {
      name: 'Receive stock',
    });

    for (const value of ['', '0', '-3', '1.5']) {
      fireEvent.change(qty, { target: { value } });
      expect(qty).toHaveAttribute('aria-invalid', 'true');
      expect(submit).toBeDisabled();
      expect(within(dialog).getByRole('alert')).toHaveTextContent(
        'Enter a whole number greater than zero.',
      );
      await user.click(submit);
    }

    expect(receiveStock).not.toHaveBeenCalled();
  });

  it('requires a non-blank adjustment note and sends it trimmed', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const adjustStock = vi.spyOn(api, 'adjustStock');
    renderWithApi(<InventoryScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Adjust SKU-1042' }));
    const dialog = await screen.findByRole('dialog');
    const note = within(dialog).getByLabelText('Reason note (required)');
    const submit = within(dialog).getByRole('button', {
      name: 'Post adjustment',
    });

    await user.type(note, '   ');
    expect(note).toHaveAttribute('aria-invalid', 'true');
    expect(submit).toBeDisabled();
    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      'Add a reason note so the count can be explained.',
    );
    await user.click(submit);
    expect(adjustStock).not.toHaveBeenCalled();

    await user.clear(note);
    await user.type(note, '  cycle count  ');
    fireEvent.change(within(dialog).getByLabelText('Adjustment'), {
      target: { value: '-2' },
    });
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(adjustStock).toHaveBeenCalledTimes(1);
    expect(adjustStock.mock.calls[0][0]).toEqual({
      sku: 'SKU-1042',
      delta: -2,
      note: 'cycle count',
    });
  });

  it('blocks zero, blank and fractional adjustment deltas before submit', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const adjustStock = vi.spyOn(api, 'adjustStock');
    renderWithApi(<InventoryScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Adjust SKU-1042' }));
    const dialog = await screen.findByRole('dialog');
    const delta = within(dialog).getByLabelText('Adjustment');
    const submit = within(dialog).getByRole('button', {
      name: 'Post adjustment',
    });

    fireEvent.change(within(dialog).getByLabelText('Reason note (required)'), {
      target: { value: 'Damaged in transit' },
    });

    for (const value of ['', '0', '1.5']) {
      fireEvent.change(delta, { target: { value } });
      expect(delta).toHaveAttribute('aria-invalid', 'true');
      expect(submit).toBeDisabled();
      expect(within(dialog).getByRole('alert')).toHaveTextContent(
        'Enter a whole number other than zero.',
      );
      await user.click(submit);
    }

    expect(adjustStock).not.toHaveBeenCalled();
  });

  it('renders a would_breach_reserved 409 in the open dialog and leaves the counters unchanged', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const adjustStock = vi.spyOn(api, 'adjustStock');
    renderWithApi(<InventoryScreen />, api);

    const list = await stockList();
    const row = await findRow(list, 'SKU-8820');

    await user.click(screen.getByRole('button', { name: 'Adjust SKU-8820' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Adjustment'), {
      target: { value: '-3' },
    });
    fireEvent.change(within(dialog).getByLabelText('Reason note (required)'), {
      target: { value: 'Damaged in transit' },
    });
    await user.click(within(dialog).getByRole('button', { name: 'Post adjustment' }));

    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent('Adjustment would breach reservations');
    expect(alert).toHaveTextContent('1 units are reserved; on hand cannot drop to 0.');
    expect(alert).toHaveTextContent(/Trace mock-\d+ · HTTP 409/);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Adjustment')).toHaveValue(-3);
    expect(within(dialog).getByLabelText('Reason note (required)')).toHaveValue(
      'Damaged in transit',
    );
    expect(adjustStock).toHaveBeenCalledTimes(1);
    expect(metric(row, 'On hand')).toBe('3');
    expect(metric(row, 'Available')).toBe('2');
  });

  it('renders a negative_on_hand 409 the same way and changes nothing', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<InventoryScreen />, api);

    const list = await stockList();
    const row = await findRow(list, 'SKU-8820');

    await user.click(screen.getByRole('button', { name: 'Adjust SKU-8820' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Adjustment'), {
      target: { value: '-5' },
    });
    fireEvent.change(within(dialog).getByLabelText('Reason note (required)'), {
      target: { value: 'Damaged in transit' },
    });
    await user.click(within(dialog).getByRole('button', { name: 'Post adjustment' }));

    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent('Adjustment would make on-hand negative');
    expect(alert).toHaveTextContent('On hand is 3; an adjustment of -5 would go below zero.');
    expect(alert).toHaveTextContent(/Trace mock-\d+ · HTTP 409/);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(metric(row, 'On hand')).toBe('3');
    expect(metric(row, 'Available')).toBe('2');
  });

  it('renders a 422 validation problem with its field errors', async () => {
    const user = userEvent.setup();
    const adjustStock = vi.fn(async () => {
      throw new ApiProblem(
        problem({
          type: 'validation_error',
          title: 'Invalid adjustment',
          status: 422,
          detail: 'Check the highlighted fields.',
          trace_id: 'trace-422',
          errors: [
            { field: 'note', message: 'Note is required.' },
            { field: 'delta', message: 'Delta must not be zero.' },
          ],
        }),
      );
    });
    const api = apiWith({ adjustStock });
    renderWithApi(<InventoryScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Adjust SKU-1042' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Adjustment'), {
      target: { value: '-2' },
    });
    fireEvent.change(within(dialog).getByLabelText('Reason note (required)'), {
      target: { value: 'Damaged in transit' },
    });
    await user.click(within(dialog).getByRole('button', { name: 'Post adjustment' }));

    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent('Invalid adjustment');
    expect(alert).toHaveTextContent('Check the highlighted fields.');
    expect(alert).toHaveTextContent(/Trace trace-422 · HTTP 422/);

    const errors = within(dialog).getByRole('list', {
      name: 'Validation errors',
    });
    expect(within(errors).getByText('note')).toBeInTheDocument();
    expect(within(errors).getByText(/Note is required\./)).toBeInTheDocument();
    expect(within(errors).getByText('delta')).toBeInTheDocument();
    expect(within(errors).getByText(/Delta must not be zero\./)).toBeInTheDocument();

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(adjustStock).toHaveBeenCalledWith({
      sku: 'SKU-1042',
      delta: -2,
      note: 'Damaged in transit',
    });
  });

  it('renders title, detail and trace id for an unrecognised problem type', async () => {
    const user = userEvent.setup();
    const receiveStock = vi.fn(async () => {
      throw new ApiProblem(
        problem({
          type: 'mystery_error',
          title: 'Something unexpected',
          status: 500,
          detail: 'The shelf robot refused.',
          trace_id: 'trace-abc',
        }),
      );
    });
    const api = apiWith({ receiveStock });
    renderWithApi(<InventoryScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Receive SKU-1042' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Receive stock' }));

    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent('Something unexpected');
    expect(alert).toHaveTextContent('The shelf robot refused.');
    expect(alert).toHaveTextContent(/Trace trace-abc · HTTP 500/);
    expect(
      within(dialog).queryByRole('list', { name: 'Validation errors' }),
    ).not.toBeInTheDocument();
  });

  it('shows one mono loading line while the stock list is in flight', async () => {
    const pending = deferred<StockRow[]>();
    const api = apiWith({ listStock: () => pending.promise });
    renderWithApi(<InventoryScreen />, api);

    const loading = screen.getAllByText('Reading the shelf…');
    expect(loading).toHaveLength(1);
    expect(loading[0]).toHaveClass('font-mono');

    await act(async () => {
      pending.resolve([]);
    });
    await waitFor(() => expect(screen.getByText('No stock yet')).toBeInTheDocument());
  });

  it('shows a dashed empty panel naming the next action', async () => {
    const api = apiWith({ listStock: async () => [] });
    renderWithApi(<InventoryScreen />, api);

    const title = await screen.findByText('No stock yet');
    expect(title.closest('.border-dashed')).not.toBeNull();
    expect(
      screen.getByText('Receive a delivery to add the first SKU to the shelf.'),
    ).toBeInTheDocument();

    const list = await stockList();
    expect(within(list).queryAllByRole('listitem')).toHaveLength(0);
  });

  it('shows the list problem notice when the stock read fails', async () => {
    const api = apiWith({
      listStock: async () => {
        throw new ApiProblem(
          problem({
            type: 'service_unavailable',
            title: 'Stock room unavailable',
            status: 503,
            detail: 'The database did not answer.',
            trace_id: 'trace-503',
          }),
        );
      },
    });
    renderWithApi(<InventoryScreen />, api);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not read stock');
    expect(alert).toHaveTextContent('The database did not answer.');
    expect(alert).toHaveTextContent(/Trace trace-503 · HTTP 503/);
  });

  it('labels the receive submit as Receiving… and disables it while posting', async () => {
    const user = userEvent.setup();
    const pending = deferred<StockRow>();
    const api = apiWith({ receiveStock: () => pending.promise });
    renderWithApi(<InventoryScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Receive SKU-1042' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Receive stock' }));

    const submit = within(dialog).getByRole('button', { name: 'Receiving…' });
    expect(submit).toBeDisabled();

    await act(async () => {
      pending.resolve(received);
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('labels the adjust submit as Posting… and disables it while posting', async () => {
    const user = userEvent.setup();
    const pending = deferred<StockRow>();
    const api = apiWith({ adjustStock: () => pending.promise });
    renderWithApi(<InventoryScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Adjust SKU-1042' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Reason note (required)'), {
      target: { value: 'Cycle count' },
    });
    await user.click(within(dialog).getByRole('button', { name: 'Post adjustment' }));

    const submit = within(dialog).getByRole('button', { name: 'Posting…' });
    expect(submit).toBeDisabled();

    await act(async () => {
      pending.resolve(received);
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('labels every dialog input and restores focus to the row action on Escape', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<InventoryScreen />, api);

    const receiveTrigger = await screen.findByRole('button', {
      name: 'Receive SKU-1042',
    });
    await user.click(receiveTrigger);
    const receiveDialog = await screen.findByRole('dialog');
    expect(receiveDialog).toHaveAttribute('aria-modal', 'true');
    expect(within(receiveDialog).getByLabelText('Quantity received')).toBeInTheDocument();
    expect(within(receiveDialog).getByLabelText('Note (optional)')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(receiveTrigger).toHaveFocus());

    const adjustTrigger = screen.getByRole('button', {
      name: 'Adjust SKU-1042',
    });
    await user.click(adjustTrigger);
    const adjustDialog = await screen.findByRole('dialog');
    expect(within(adjustDialog).getByLabelText('Adjustment')).toBeInTheDocument();
    expect(within(adjustDialog).getByLabelText('Reason note (required)')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(adjustTrigger).toHaveFocus());
  });
});
