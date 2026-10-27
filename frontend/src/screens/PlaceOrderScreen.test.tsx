import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

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
});
