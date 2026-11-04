import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('the default api export', () => {
  it('is the real HTTP client and honours VITE_API_BASE_URL', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.test');

    const requests: string[] = [];
    vi.stubGlobal('fetch', async (request: Request) => {
      const url = new URL(request.url);
      requests.push(`${request.method} ${url.pathname}${url.search}`);
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });

    vi.resetModules();
    const { api, createMockApi } = await import('./index');

    expect(typeof createMockApi).toBe('function');
    await expect(api.listStock()).resolves.toEqual([]);
    expect(requests).toEqual(['GET /api/stock']);
  });

  it('fetches the order surface through the same client', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.test');

    const requests: string[] = [];
    vi.stubGlobal('fetch', async (request: Request) => {
      const url = new URL(request.url);
      requests.push(`${request.method} ${url.pathname}${url.search}`);
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });

    vi.resetModules();
    const { api } = await import('./index');

    await api.listOrders('confirmed');
    expect(requests).toEqual(['GET /api/orders?status=confirmed']);
  });
});
