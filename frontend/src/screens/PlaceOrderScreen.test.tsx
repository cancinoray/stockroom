import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { createMockApi } from '../api/mock';
import { renderWithApi } from '../test/render';
import PlaceOrderScreen from './PlaceOrderScreen';

describe('place order', () => {
  it('names the short line and does not create the order', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<PlaceOrderScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Add SKU-5127' }));

    const quantity = screen.getByLabelText('Quantity for SKU-5127');
    await user.clear(quantity);
    await user.type(quantity, '6');

    await user.type(screen.getByLabelText('Customer reference'), 'CUST-123');
    await user.click(screen.getByRole('button', { name: 'Reserve stock' }));

    expect(await screen.findByText(/short by 1/i)).toBeInTheDocument();
    expect(await api.listOrders()).toHaveLength(5);
  });

  it('blocks a zero quantity before calling the API', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    const createOrder = vi.spyOn(api, 'createOrder');
    renderWithApi(<PlaceOrderScreen />, api);

    await user.click(await screen.findByRole('button', { name: 'Add SKU-5127' }));

    const quantity = screen.getByLabelText('Quantity for SKU-5127');
    await user.clear(quantity);
    await user.type(quantity, '0');
    await user.type(screen.getByLabelText('Customer reference'), 'CUST-123');

    expect(screen.getByText(/whole number greater than zero/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reserve stock' })).toBeDisabled();
    expect(createOrder).not.toHaveBeenCalled();
  });
});
