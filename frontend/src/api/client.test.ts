import { afterEach, describe, expect, it, vi } from 'vitest';

import { createHttpApi, createHttpClient, resolveApiBaseUrl } from './client';
import { isApiProblem } from './types';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('HTTP client base URL', () => {
  it('is same-origin by default', () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    expect(resolveApiBaseUrl()).toBe('');
  });

  it('is overridable with VITE_API_BASE_URL', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000');
    expect(resolveApiBaseUrl()).toBe('http://localhost:8000');
  });
});

describe('HTTP client calls the §7 surface', () => {
  it('uses the contract paths, verbs and request bodies', async () => {
    const calls: string[] = [];
    const stockRow = {
      sku: 'SKU-1042',
      name: 'Desk lamp, matte black',
      on_hand: 3,
      reserved: 0,
      available: 3,
      reorder_point: 1,
      unit_price_cents: 100,
      low: false,
    };
    const order = {
      id: 'ord-1',
      customer_ref: 'CUST-1',
      status: 'confirmed',
      created_at: '2026-11-04T00:00:00Z',
      lines: [],
      movements: [],
    };

    const api = createHttpApi({
      baseUrl: 'http://api.test',
      fetch: async (request) => {
        const url = new URL(request.url);
        calls.push(`${request.method} ${url.pathname}${url.search}`);
        if (url.pathname === '/api/products') {
          return jsonResponse([
            {
              sku: 'SKU-1042',
              name: 'Desk lamp, matte black',
              unit_price_cents: 100,
              reorder_point: 1,
              available: 3,
              low: false,
            },
          ]);
        }
        if (url.pathname.includes('/movements')) {
          return jsonResponse([]);
        }
        if (url.pathname === '/api/invariants') {
          return jsonResponse({ ok: true, violations: [] });
        }
        if (url.pathname.startsWith('/api/orders/')) {
          return jsonResponse(order);
        }
        if (url.pathname === '/api/orders') {
          return jsonResponse([]);
        }
        return jsonResponse(stockRow);
      },
    });

    await api.listProducts();
    await api.listStock();
    await api.receiveStock({ sku: 'SKU-1042', qty: 2 });
    await api.adjustStock({ sku: 'SKU-1042', delta: -1, note: 'Damaged' });
    await api.listMovements('SKU-1042');
    await api.listOrders();
    await api.listOrders('confirmed');
    await api.getOrder('ord-1');
    await api.createOrder({
      customer_ref: 'CUST-1',
      lines: [{ sku: 'SKU-1042', qty: 1 }],
    });
    await api.cancelOrder('ord-1');
    await api.fulfilOrder('ord-1');
    await api.listInvariants();

    expect(calls).toEqual([
      'GET /api/products',
      'GET /api/stock',
      'POST /api/stock/receive',
      'POST /api/stock/adjust',
      'GET /api/stock/SKU-1042/movements',
      'GET /api/orders',
      'GET /api/orders?status=confirmed',
      'GET /api/orders/ord-1',
      'POST /api/orders',
      'POST /api/orders/ord-1/cancel',
      'POST /api/orders/ord-1/fulfil',
      'GET /api/invariants',
    ]);
  });
});

describe('HTTP client error normalization', () => {
  it('throws the normalized problem with its trace id and line errors', async () => {
    const body = {
      type: 'insufficient_stock',
      title: 'Not enough stock',
      status: 409,
      detail: 'SKU-4410 is short. No stock was reserved.',
      trace_id: 'trace-409',
      errors: [{ sku: 'SKU-4410', requested: 6, available: 5, short_by: 1 }],
    };
    const api = createHttpApi({
      baseUrl: 'http://api.test',
      fetch: async () => jsonResponse(body, 409),
    });

    const error = await api
      .createOrder({
        customer_ref: 'CUST-1',
        lines: [{ sku: 'SKU-4410', qty: 6 }],
      })
      .catch((cause: unknown) => cause);

    expect(isApiProblem(error)).toBe(true);
    if (!isApiProblem(error)) {
      throw new Error('expected an ApiProblem');
    }
    expect(error.problem.type).toBe('insufficient_stock');
    expect(error.problem.status).toBe(409);
    expect(error.problem.trace_id).toBe('trace-409');
    expect(error.problem.errors?.[0]).toMatchObject({
      sku: 'SKU-4410',
      requested: 6,
      available: 5,
      short_by: 1,
    });
  });

  it('turns a non-JSON error body into a generic problem', async () => {
    const api = createHttpApi({
      baseUrl: 'http://api.test',
      fetch: async () =>
        new Response('<html>bad gateway</html>', {
          status: 502,
          headers: { 'content-type': 'text/html' },
        }),
    });

    const error = await api.listStock().catch((cause: unknown) => cause);

    expect(isApiProblem(error)).toBe(true);
    if (!isApiProblem(error)) {
      throw new Error('expected an ApiProblem');
    }
    expect(error.problem.type).toBe('unexpected');
    expect(error.problem.status).toBe(502);
    expect(error.problem.trace_id.length).toBeGreaterThan(0);
  });

  it('turns a network failure into a generic problem', async () => {
    const api = createHttpApi({
      baseUrl: 'http://api.test',
      fetch: async () => {
        throw new TypeError('Failed to fetch');
      },
    });

    const error = await api.listStock().catch((cause: unknown) => cause);

    expect(isApiProblem(error)).toBe(true);
    if (!isApiProblem(error)) {
      throw new Error('expected an ApiProblem');
    }
    expect(error.problem.type).toBe('unexpected');
    expect(error.problem.status).toBe(500);
    expect(error.problem.title.length).toBeGreaterThan(0);
  });
});

describe('generated client typing', () => {
  it.skip('rejects a wrong path, verb or request body at compile time', () => {
    const client = createHttpClient({ baseUrl: 'http://api.test' });

    // @ts-expect-error '/api/not-a-path' is not in the generated contract.
    void client.GET('/api/not-a-path');
    // @ts-expect-error GET /api/stock has no POST operation.
    void client.POST('/api/stock');
    // @ts-expect-error ReceiveRequest requires qty.
    void client.POST('/api/stock/receive', { body: { sku: 'SKU-1042' } });
    // The correct call compiles.
    void client.POST('/api/stock/receive', {
      body: { sku: 'SKU-1042', qty: 1 },
    });
  });
});
