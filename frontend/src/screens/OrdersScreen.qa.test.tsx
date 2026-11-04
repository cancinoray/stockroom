import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { Order, StockroomApi } from '../api';
import { createMockApi } from '../api/mock';
import { renderWithApi } from '../test/render';
import OrdersScreen from './OrdersScreen';

/**
 * QA coverage for the acceptance criteria issue #30 describes but the shipped
 * suite does not assert: the fulfil-side 409 and pending states (US4-AC3, and
 * "Fulfilling… with both actions disabled"), fulfil disabled on an already
 * fulfilled order, and the per-filter empty states beyond Cancelled.
 */

function list() {
  return screen.getByRole('list', { name: 'Orders' });
}

async function openOrder(customerRef: RegExp) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: customerRef }));
  const dialog = await screen.findByRole('dialog');
  return { user, dialog };
}

describe('orders (QA)', () => {
  it('renders a 409 from a repeated fulfil as a problem notice without shipping twice', async () => {
    const user = userEvent.setup();
    const inner = createMockApi({ latencyMs: 0 });
    const staleList = await inner.listOrders();
    const staleOrder = await inner.getOrder('ord-1001');
    await inner.fulfilOrder('ord-1001');

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

    await user.click(within(dialog).getByRole('button', { name: 'Fulfil order' }));

    const notice = await within(dialog).findByRole('alert');
    expect(notice).toHaveTextContent('Invalid transition');
    expect(notice).toHaveTextContent('A fulfilled order cannot be fulfilled.');
    expect(notice).toHaveTextContent(/Trace mock-\d+/);

    await waitFor(() => expect(dialog).toHaveTextContent('fulfilled'));
    expect(within(list()).getByRole('button', { name: /CUST-88/ })).toHaveTextContent('fulfilled');
    expect(within(dialog).getAllByText('ship')).toHaveLength(2);
    expect(within(dialog).getByRole('button', { name: 'Cancel order' })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Fulfil order' })).toBeDisabled();

    const stored = await inner.getOrder('ord-1001');
    expect(stored.movements.filter((movement) => movement.reason === 'ship')).toHaveLength(2);
  });

  it('disables fulfil for an already fulfilled order', async () => {
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<OrdersScreen />, api);

    const { dialog } = await openOrder(/CUST-42/);
    await within(dialog).findByText('SKU-2087');

    expect(within(dialog).getByRole('heading', { level: 2 })).toHaveTextContent('CUST-42');
    expect(within(dialog).getByRole('button', { name: 'Fulfil order' })).toBeDisabled();
  });

  it('shows Fulfilling… with both actions disabled while the fulfil is pending', async () => {
    const api = createMockApi({ latencyMs: 0 });
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const gated: StockroomApi = {
      ...api,
      fulfilOrder: async (id): Promise<Order> => {
        await gate;
        return api.fulfilOrder(id);
      },
    };
    renderWithApi(<OrdersScreen />, gated);

    const { user, dialog } = await openOrder(/CUST-63/);
    await within(dialog).findByText('SKU-4410');

    await user.click(within(dialog).getByRole('button', { name: 'Fulfil order' }));

    expect(within(dialog).getByRole('button', { name: 'Fulfilling…' })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Cancel order' })).toBeDisabled();

    release();
    await waitFor(() => expect(dialog).toHaveTextContent('fulfilled'));
  });

  it('shows a per-filter empty state for a status with no rows and no error notice', async () => {
    const user = userEvent.setup();
    const inner = createMockApi({ latencyMs: 0 });
    const api: StockroomApi = {
      ...inner,
      listOrders: async (status) => (status === 'fulfilled' ? [] : inner.listOrders(status)),
    };
    renderWithApi(<OrdersScreen />, api);

    await screen.findByRole('button', { name: /CUST-88/ });
    await user.click(screen.getByRole('button', { name: 'Fulfilled' }));

    expect(await screen.findByText('No fulfilled orders')).toBeInTheDocument();
    expect(screen.getByText(/Fulfilling a confirmed order/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(within(list()).queryAllByRole('button')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Fulfilled' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });
});
