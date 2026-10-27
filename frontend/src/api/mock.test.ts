import { describe, expect, it } from 'vitest';

import { createMockApi } from './mock';
import { ApiProblem } from './types';

describe('mock stockroom api', () => {
  it('rejects the whole order when one line is short, and reserves nothing', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const stockBefore = await api.listStock();
    const ordersBefore = await api.listOrders();

    const error = await api
      .createOrder({
        customer_ref: 'CUST-123',
        lines: [
          { sku: 'SKU-1042', qty: 2 },
          { sku: 'SKU-4410', qty: 1 },
        ],
      })
      .catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiProblem);
    if (!(error instanceof ApiProblem)) {
      throw new Error('expected an ApiProblem');
    }
    expect(error.problem.type).toBe('insufficient_stock');
    expect(error.problem.errors?.[0]).toMatchObject({
      sku: 'SKU-4410',
      requested: 1,
      available: 0,
      short_by: 1,
    });
    expect(await api.listStock()).toEqual(stockBefore);
    expect(await api.listOrders()).toHaveLength(ordersBefore.length);
  });

  it('reserves every line of an accepted order', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const stockBefore = await api.listStock();

    const order = await api.createOrder({
      customer_ref: 'CUST-123',
      lines: [
        { sku: 'SKU-1042', qty: 2 },
        { sku: 'SKU-3301', qty: 3 },
      ],
    });

    expect(order.status).toBe('confirmed');
    expect(order.lines).toHaveLength(2);
    expect(order.movements.filter((movement) => movement.reason === 'reserve')).toHaveLength(2);

    const stockAfter = await api.listStock();
    const lampBefore = stockBefore.find((row) => row.sku === 'SKU-1042');
    const lampAfter = stockAfter.find((row) => row.sku === 'SKU-1042');
    expect(lampAfter?.reserved).toBe((lampBefore?.reserved ?? 0) + 2);
    expect(lampAfter?.available).toBe((lampBefore?.available ?? 0) - 2);
  });

  it('releases the hold when an order is cancelled', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const availableBefore = (await api.listStock()).find(
      (row) => row.sku === 'SKU-1042',
    )?.available;

    const created = await api.createOrder({
      customer_ref: 'CUST-123',
      lines: [{ sku: 'SKU-1042', qty: 2 }],
    });
    const cancelled = await api.cancelOrder(created.id);

    expect(cancelled.status).toBe('cancelled');
    expect(
      (await api.listStock()).find((row) => row.sku === 'SKU-1042')?.available,
    ).toBe(availableBefore);
    expect(await api.cancelOrder(created.id).catch((error: unknown) => error)).toBeInstanceOf(
      ApiProblem,
    );
  });

  it('moves on-hand and reserved together when an order is fulfilled', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const before = (await api.listStock()).find((row) => row.sku === 'SKU-2087');

    const created = await api.createOrder({
      customer_ref: 'CUST-123',
      lines: [{ sku: 'SKU-2087', qty: 1 }],
    });
    const reserved = (await api.listStock()).find((row) => row.sku === 'SKU-2087');
    const fulfilled = await api.fulfilOrder(created.id);

    expect(fulfilled.status).toBe('fulfilled');
    const after = (await api.listStock()).find((row) => row.sku === 'SKU-2087');
    expect(after?.on_hand).toBe((reserved?.on_hand ?? 0) - 1);
    expect(after?.reserved).toBe((reserved?.reserved ?? 0) - 1);
    expect(after?.available).toBe(reserved?.available);
    expect(after?.reserved).toBe(before?.reserved);
  });

  it('receives stock and refuses an adjustment that would breach reservations', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const before = (await api.listStock()).find((row) => row.sku === 'SKU-4410');

    const received = await api.receiveStock({
      sku: 'SKU-4410',
      qty: 2,
      note: 'Delivery D-77',
    });
    expect(received.on_hand).toBe((before?.on_hand ?? 0) + 2);

    const error = await api
      .adjustStock({ sku: 'SKU-4410', delta: -7, note: 'Damaged in transit' })
      .catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiProblem);
    if (!(error instanceof ApiProblem)) {
      throw new Error('expected an ApiProblem');
    }
    expect(error.problem.type).toBe('would_breach_reserved');
    expect(
      (await api.listStock()).find((row) => row.sku === 'SKU-4410')?.on_hand,
    ).toBe(received.on_hand);
  });
});
