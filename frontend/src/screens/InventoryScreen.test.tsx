import { screen, waitFor, within } from '@testing-library/react';
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

    const trigger = await screen.findByRole('button', { name: 'Receive SKU-1042' });
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
});
