import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { createMockApi } from '../api/mock';
import { renderWithApi } from '../test/render';
import InventoryScreen from './InventoryScreen';

describe('inventory', () => {
  it('marks low stock and opens the movement ledger without leaving the page', async () => {
    const user = userEvent.setup();
    const api = createMockApi({ latencyMs: 0 });
    renderWithApi(<InventoryScreen />, api);

    const shelf = await screen.findByRole('list', { name: 'Stock on hand' });
    await within(shelf).findByText('SKU-1042');
    expect(within(shelf).getAllByText('Low')).toHaveLength(4);
    expect(within(shelf).getByText('SKU-5127')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Movement history for SKU-1042' }));

    expect(await screen.findByText(/Opening count/)).toBeInTheDocument();
    expect(screen.getByText('Why this count?')).toBeInTheDocument();
  });
});
