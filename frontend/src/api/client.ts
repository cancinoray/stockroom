import createClient, { type ClientOptions } from 'openapi-fetch';

import { toApiProblem } from './problem';
import type { paths } from './schema';
import type {
  AdjustInput,
  CreateOrderInput,
  InvariantReport,
  Movement,
  Order,
  OrderStatus,
  Product,
  ReceiveInput,
  StockRow,
  StockroomApi,
} from './types';

/**
 * The client is same-origin by default so the built app talks to `/api` on its
 * own host. `VITE_API_BASE_URL` points it at the running dev stack instead.
 */
export function resolveApiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? '';
}

export function createHttpClient(options: ClientOptions = {}) {
  return createClient<paths>({ baseUrl: resolveApiBaseUrl(), ...options });
}

interface OperationResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/**
 * Every call funnels through here: an error body becomes the normalized
 * problem, a missing body becomes the generic problem, and a rejected fetch is
 * converted instead of escaping as a transport error.
 */
async function request<T>(
  operation: () => Promise<OperationResult<T>>,
): Promise<T> {
  let result: OperationResult<T>;
  try {
    result = await operation();
  } catch (cause) {
    throw toApiProblem(cause);
  }

  const { data, error, response } = result;

  if (error !== undefined) {
    throw toApiProblem(error, {
      status: response.status,
      traceId: response.headers.get('x-trace-id') ?? undefined,
    });
  }

  if (data === undefined || data === null) {
    throw toApiProblem(undefined, { status: response.status });
  }

  return data;
}

/**
 * The behavior surface from `types.ts`, implemented against the generated
 * `openapi-fetch` client. Hand-built, because a generator cannot know how the
 * order-desk screens want to compose these calls.
 */
export function createHttpApi(options: ClientOptions = {}): StockroomApi {
  const client = createHttpClient(options);

  return {
    listProducts: () => request<Product[]>(() => client.GET('/api/products')),

    listStock: () => request<StockRow[]>(() => client.GET('/api/stock')),

    listMovements: (sku) =>
      request<Movement[]>(() =>
        client.GET('/api/stock/{sku}/movements', { params: { path: { sku } } }),
      ),

    receiveStock: (input: ReceiveInput) =>
      request<StockRow>(() =>
        client.POST('/api/stock/receive', { body: input }),
      ),

    adjustStock: (input: AdjustInput) =>
      request<StockRow>(() =>
        client.POST('/api/stock/adjust', { body: input }),
      ),

    listOrders: (status?: OrderStatus) =>
      request<Order[]>(() =>
        client.GET('/api/orders', {
          params: { query: status ? { status } : {} },
        }),
      ),

    getOrder: (id) =>
      request<Order>(() =>
        client.GET('/api/orders/{id}', { params: { path: { id } } }),
      ),

    createOrder: (input: CreateOrderInput) =>
      request<Order>(() => client.POST('/api/orders', { body: input })),

    cancelOrder: (id) =>
      request<Order>(() =>
        client.POST('/api/orders/{id}/cancel', { params: { path: { id } } }),
      ),

    fulfilOrder: (id) =>
      request<Order>(() =>
        client.POST('/api/orders/{id}/fulfil', { params: { path: { id } } }),
      ),

    listInvariants: () =>
      request<InvariantReport>(() => client.GET('/api/invariants')),
  };
}

/** The running app's client. Screens reach it through `useStockroomApi()`. */
export const api = createHttpApi();
