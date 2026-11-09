import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiProblem, type OrderStatus, type StockroomApi } from '../api';
import { createMockApi } from '../api/mock';
import { formatDateTime, formatMoney } from '../lib/format';
import { renderWithApi } from '../test/render';
import OrdersScreen from './OrdersScreen';

function list() {
  return screen.getByRole('list', { name: 'Orders' });
}

async function openOrder(customerRef: RegExp) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: customerRef }));
  const dialog = await screen.findByRole('dialog');
  return { user, dialog };
}

describe('orders', () => {
  it('lists every order newest first with id, customer ref, status and created time', async () => {
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<OrdersScreen />, api);

    const orders = await screen.findByRole('list', { name: 'Orders' });
    await within(orders).findByText('CUST-88');

    expect(within(orders).getAllByText(/^#\d+$/).map((node) => node.textContent)).toEqual([
      '#1005',
      '#1004',
      '#1003',
      '#1002',
      '#1001',
    ]);
    expect(within(orders).getAllByText('confirmed')).toHaveLength(3);
    expect(within(orders).getByText('fulfilled')).toBeInTheDocument();
    expect(within(orders).getByText('cancelled')).toBeInTheDocument();
    expect(within(orders).getByRole('button', { name: /CUST-29/ })).toHaveTextContent(
      formatDateTime('2026-10-27T08:10:00Z'),
    );
  });

  it('orders the list newest first even when the API returns another order', async () => {
    const inner = createMockApi({ latencyMs: 0 });
    const api: StockroomApi = {
      ...inner,
      listOrders: async (status) => (await inner.listOrders(status)).reverse(),
    };
    renderWithApi(<OrdersScreen />, api);

    await screen.findByText('CUST-88');
    expect(within(list()).getAllByText(/^#\d+$/).map((node) => node.textContent)).toEqual([
      '#1005',
      '#1004',
      '#1003',
      '#1002',
      '#1001',
    ]);
  });

  it('opens the order detail in place with lines, snapshotted prices, reservations and total', async () => {
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<OrdersScreen />, api);

    const { dialog } = await openOrder(/CUST-88/);
    await within(dialog).findByText('SKU-1042');

    const lamp = within(dialog).getByRole('row', { name: /SKU-1042/ });
    expect(within(lamp).getByText('Desk lamp, matte black')).toBeInTheDocument();
    expect(within(lamp).getByText('2')).toBeInTheDocument();
    expect(within(lamp).getByText(formatMoney(129_900))).toBeInTheDocument();
    expect(within(lamp).getByText(formatMoney(259_800))).toBeInTheDocument();
    expect(lamp).toHaveTextContent('reserve +2');

    const paper = within(dialog).getByRole('row', { name: /SKU-3301/ });
    expect(paper).toHaveTextContent('reserve +4');
    expect(within(paper).getByText(formatMoney(115_600))).toBeInTheDocument();

    expect(within(dialog).getByText(formatMoney(375_400))).toBeInTheDocument();
    expect(within(dialog).getByRole('heading', { name: 'Movement timeline' })).toBeInTheDocument();
  });

  it('shows the timeline newest first with reason, actor, note, order ref, deltas and balance', async () => {
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<OrdersScreen />, api);

    const { dialog } = await openOrder(/CUST-42/);
    const ledger = await within(dialog).findByRole('list', { name: 'Movement ledger' });
    const entries = within(ledger).getAllByRole('listitem');

    expect(entries).toHaveLength(2);
    expect(entries[0]).toHaveTextContent('ship');
    expect(entries[1]).toHaveTextContent('reserve');

    expect(entries[0]).toHaveTextContent('Ship ord-1002');
    expect(entries[0]).toHaveTextContent('demo-operator');
    expect(entries[0]).toHaveTextContent('#1002');
    expect(entries[0]).toHaveTextContent('-1');
    expect(entries[0]).toHaveTextContent('9');

    expect(entries[1]).toHaveTextContent('—');
    expect(entries[1]).toHaveTextContent('+1');
    expect(entries[1]).toHaveTextContent('10');

    expect(within(dialog).getByText('fulfilled')).toBeInTheDocument();
  });

  it('requests the chosen status, marks it pressed, clears the selection and shows an empty state', async () => {
    const user = userEvent.setup();
    const inner = createMockApi({ latencyMs: 0 });
    const requested: (OrderStatus | undefined)[] = [];
    const api: StockroomApi = {
      ...inner,
      listOrders: async (status) => {
        requested.push(status);
        if (status === 'cancelled') {
          return [];
        }
        return inner.listOrders(status);
      },
    };
    renderWithApi(<OrdersScreen />, api);

    await openOrder(/CUST-88/);
    expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: 'Cancelled' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancelled' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'false');

    expect(await screen.findByText('No cancelled orders')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    expect(requested[0]).toBeUndefined();
    expect(requested).toContain('cancelled');
  });

  it('offers cancel only for confirmed orders and shows the row and detail cancelled after 200', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const cancelOrder = vi.spyOn(api, 'cancelOrder');
    renderWithApi(<OrdersScreen />, api);

    const { user, dialog } = await openOrder(/CUST-88/);
    await within(dialog).findByText('SKU-1042');

    const cancel = within(dialog).getByRole('button', { name: 'Cancel order' });
    expect(cancel).toBeEnabled();
    expect(within(dialog).getByRole('button', { name: 'Fulfil order' })).toBeEnabled();

    await user.click(cancel);

    await waitFor(() => expect(dialog).toHaveTextContent('cancelled'));
    expect(within(dialog).getAllByText('release')).toHaveLength(2);
    expect(within(dialog).getByRole('row', { name: /SKU-1042/ })).toHaveTextContent('release -2');
    expect(within(dialog).getByRole('row', { name: /SKU-3301/ })).toHaveTextContent('release -4');
    expect(within(list()).getByRole('button', { name: /CUST-88/ })).toHaveTextContent('cancelled');
    expect(cancelOrder).toHaveBeenCalledTimes(1);

    expect(within(dialog).getByRole('button', { name: 'Cancel order' })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Fulfil order' })).toBeDisabled();
  });

  it('renders a 409 from a repeated cancel without releasing twice or re-enabling the actions', async () => {
    const user = userEvent.setup();
    const inner = createMockApi({ latencyMs: 0 });
    const staleList = await inner.listOrders();
    const staleOrder = await inner.getOrder('ord-1001');
    await inner.cancelOrder('ord-1001');

    let listServed = false;
    let detailServed = false;
    const api: StockroomApi = {
      ...inner,
      listOrders: async (status) => {
        if (!listServed) {
          listServed = true;
          return staleList.filter((order) => !status || order.status === status);
        }
        return inner.listOrders(status);
      },
      getOrder: async (id) => {
        if (!detailServed) {
          detailServed = true;
          return staleOrder;
        }
        return inner.getOrder(id);
      },
    };
    renderWithApi(<OrdersScreen />, api);

    await user.click(await screen.findByRole('button', { name: /CUST-88/ }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText('SKU-1042');

    await user.click(within(dialog).getByRole('button', { name: 'Cancel order' }));

    const notice = await within(dialog).findByRole('alert');
    expect(notice).toHaveTextContent('Invalid transition');
    expect(notice).toHaveTextContent('A cancelled order cannot be cancelled.');
    expect(notice).toHaveTextContent(/Trace mock-\d+/);

    await waitFor(() => expect(dialog).toHaveTextContent('cancelled'));
    expect(within(list()).getByRole('button', { name: /CUST-88/ })).toHaveTextContent('cancelled');
    expect(within(dialog).getAllByText('release')).toHaveLength(2);
    expect(within(dialog).getByRole('button', { name: 'Cancel order' })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Fulfil order' })).toBeDisabled();

    const stored = await inner.getOrder('ord-1001');
    expect(stored.movements.filter((movement) => movement.reason === 'release')).toHaveLength(2);
  });

  it('disables cancel for fulfilled and cancelled orders', async () => {
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<OrdersScreen />, api);

    const fulfilled = await openOrder(/CUST-42/);
    await within(fulfilled.dialog).findByText('SKU-2087');
    expect(within(fulfilled.dialog).getByRole('button', { name: 'Cancel order' })).toBeDisabled();

    await fulfilled.user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    const cancelled = await openOrder(/CUST-17/);
    await within(cancelled.dialog).findByText('SKU-7714');
    expect(within(cancelled.dialog).getByRole('button', { name: 'Cancel order' })).toBeDisabled();
    expect(within(cancelled.dialog).getByRole('button', { name: 'Fulfil order' })).toBeDisabled();
  });

  it('offers fulfil only for confirmed orders and ships the lines after 200', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const fulfilOrder = vi.spyOn(api, 'fulfilOrder');
    renderWithApi(<OrdersScreen />, api);

    const { user, dialog } = await openOrder(/CUST-63/);
    await within(dialog).findByText('SKU-4410');

    const fulfil = within(dialog).getByRole('button', { name: 'Fulfil order' });
    expect(fulfil).toBeEnabled();
    await user.click(fulfil);

    await waitFor(() => expect(dialog).toHaveTextContent('fulfilled'));
    expect(within(dialog).getAllByText('ship')).toHaveLength(2);
    expect(within(dialog).getByRole('row', { name: /SKU-1042/ })).toHaveTextContent('ship -1');
    expect(within(dialog).getByRole('row', { name: /SKU-4410/ })).toHaveTextContent('ship -5');
    expect(within(list()).getByRole('button', { name: /CUST-63/ })).toHaveTextContent('fulfilled');
    expect(fulfilOrder).toHaveBeenCalledTimes(1);
    expect(within(dialog).getByRole('button', { name: 'Fulfil order' })).toBeDisabled();
  });

  it('shows a not-found notice on a 404 and leaves the list usable', async () => {
    const user = userEvent.setup();
    const inner = createMockApi({ latencyMs: 0 });
    const api: StockroomApi = {
      ...inner,
      getOrder: async (id) => {
        if (id === 'ord-1005') {
          throw new ApiProblem({
            type: 'not_found',
            title: 'Not found',
            status: 404,
            detail: 'Order ord-1005 does not exist.',
            trace_id: 'trace-orders-404',
          });
        }
        return inner.getOrder(id);
      },
    };
    renderWithApi(<OrdersScreen />, api);

    await user.click(await screen.findByRole('button', { name: /CUST-29/ }));
    const dialog = await screen.findByRole('dialog');

    const notice = await within(dialog).findByRole('alert');
    expect(notice).toHaveTextContent('Not found');
    expect(notice).toHaveTextContent('Order ord-1005 does not exist.');
    expect(notice).toHaveTextContent('trace-orders-404');
    expect(within(dialog).queryByRole('table')).not.toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /CUST-88/ }));
    const reopened = await screen.findByRole('dialog');
    expect(await within(reopened).findByText('SKU-1042')).toBeInTheDocument();
  });

  it('shows the mono loading line before the order book arrives', async () => {
    const api = createMockApi({ latencyMs: 40 });
    renderWithApi(<OrdersScreen />, api);

    expect(screen.getByText('Reading orders…')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /CUST-88/ })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText('Reading orders…')).not.toBeInTheDocument(),
    );
  });

  it('renders a list error with a trace id instead of an empty state', async () => {
    const inner = createMockApi({ latencyMs: 0 });
    const api: StockroomApi = {
      ...inner,
      listOrders: async () => {
        throw new ApiProblem({
          type: 'unexpected',
          title: 'Order book unavailable',
          status: 500,
          detail: 'The order book could not be read.',
          trace_id: 'trace-orders-500',
        });
      },
    };
    renderWithApi(<OrdersScreen />, api);

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent('Order book unavailable');
    expect(notice).toHaveTextContent('The order book could not be read.');
    expect(notice).toHaveTextContent('trace-orders-500');
    expect(screen.queryByText('No orders yet')).not.toBeInTheDocument();
  });

  it('shows Cancelling… with both actions disabled while the mutation is pending', async () => {
    const api = createMockApi({ latencyMs: 0 });
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const gated: StockroomApi = {
      ...api,
      cancelOrder: async (id) => {
        await gate;
        return api.cancelOrder(id);
      },
    };
    renderWithApi(<OrdersScreen />, gated);

    const { user, dialog } = await openOrder(/CUST-88/);
    await within(dialog).findByText('SKU-1042');

    await user.click(within(dialog).getByRole('button', { name: 'Cancel order' }));

    expect(within(dialog).getByRole('button', { name: 'Cancelling…' })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Fulfil order' })).toBeDisabled();

    release();
    await waitFor(() => expect(dialog).toHaveTextContent('cancelled'));
  });

  it('marks the selected row aria-current, traps Tab, closes on Escape and restores focus', async () => {
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<OrdersScreen />, api);

    const row = await screen.findByRole('button', { name: /CUST-88/ });
    expect(row).not.toHaveAttribute('aria-current');

    const { user, dialog } = await openOrder(/CUST-88/);
    await within(dialog).findByText('SKU-1042');

    expect(dialog).toHaveFocus();
    expect(row).toHaveAttribute('aria-current', 'true');

    await user.tab({ shift: true });
    expect(within(dialog).getByRole('button', { name: 'Fulfil order' })).toHaveFocus();

    await user.tab();
    expect(within(dialog).getByRole('button', { name: 'Close order' })).toHaveFocus();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(row).toHaveFocus());
    expect(row).not.toHaveAttribute('aria-current');
  });
});
