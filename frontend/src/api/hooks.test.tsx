import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { StockroomApiProvider } from './context';
import {
  queryKeys,
  useAdjustStock,
  useCancelOrder,
  useCreateOrder,
  useFulfilOrder,
  useInvariants,
  useMovements,
  useOrder,
  useOrders,
  useProducts,
  useReceiveStock,
  useStock,
} from './hooks';
import { createMockApi } from './mock';

function setup() {
  const api = createMockApi({ latencyMs: 0 });
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <StockroomApiProvider api={api}>{children}</StockroomApiProvider>
      </QueryClientProvider>
    );
  }

  return { api, queryClient, wrapper: Wrapper };
}

describe('query keys', () => {
  it('are stable for the whole §7 surface', () => {
    expect(queryKeys.products).toEqual(['products']);
    expect(queryKeys.stock).toEqual(['stock']);
    expect(queryKeys.movements('SKU-1042')).toEqual(['movements', 'SKU-1042']);
    expect(queryKeys.orders('all')).toEqual(['orders', 'all']);
    expect(queryKeys.orders('confirmed')).toEqual(['orders', 'confirmed']);
    expect(queryKeys.order('ord-1001')).toEqual(['order', 'ord-1001']);
    expect(queryKeys.invariants).toEqual(['invariants']);
  });
});

describe('query hooks', () => {
  it('reads products under ["products"]', async () => {
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => useProducts(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(8);
    expect(queryClient.getQueryData(queryKeys.products)).toBeDefined();
  });

  it('reads stock under ["stock"]', async () => {
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => useStock(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(queryClient.getQueryData(queryKeys.stock)).toBeDefined();
  });

  it('reads a SKU ledger under ["movements", sku]', async () => {
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => useMovements('SKU-1042'), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(
      queryClient.getQueryData(queryKeys.movements('SKU-1042')),
    ).toBeDefined();
  });

  it('keeps the order list keyed by status and omits the filter for "all"', async () => {
    const { api, queryClient, wrapper } = setup();
    const listOrders = vi.spyOn(api, 'listOrders');

    const all = renderHook(() => useOrders('all'), { wrapper });
    await waitFor(() => expect(all.result.current.isSuccess).toBe(true));
    expect(queryClient.getQueryData(queryKeys.orders('all'))).toBeDefined();
    expect(listOrders).toHaveBeenLastCalledWith(undefined);

    const confirmed = renderHook(() => useOrders('confirmed'), { wrapper });
    await waitFor(() => expect(confirmed.result.current.isSuccess).toBe(true));
    expect(
      queryClient.getQueryData(queryKeys.orders('confirmed')),
    ).toBeDefined();
    expect(listOrders).toHaveBeenLastCalledWith('confirmed');
  });

  it('reads one order under ["order", id]', async () => {
    const { api, queryClient, wrapper } = setup();
    const getOrder = vi.spyOn(api, 'getOrder');

    const { result } = renderHook(() => useOrder('ord-1001'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getOrder).toHaveBeenCalledWith('ord-1001');
    expect(queryClient.getQueryData(queryKeys.order('ord-1001'))).toBeDefined();
  });

  it('reads the invariant report under ["invariants"]', async () => {
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => useInvariants(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(queryClient.getQueryData(queryKeys.invariants)).toEqual({
      ok: true,
      violations: [],
    });
  });
});

describe('mutation invalidation', () => {
  it('receive invalidates stock, that SKU ledger and the invariant report', async () => {
    const { queryClient, wrapper } = setup();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    const setQueryData = vi.spyOn(queryClient, 'setQueryData');
    const { result } = renderHook(() => useReceiveStock(), { wrapper });

    act(() => result.current.mutate({ sku: 'SKU-1042', qty: 1 }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.stock });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.movements('SKU-1042'),
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.invariants });
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it('adjust invalidates stock, that SKU ledger and the invariant report', async () => {
    const { queryClient, wrapper } = setup();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    const setQueryData = vi.spyOn(queryClient, 'setQueryData');
    const { result } = renderHook(() => useAdjustStock(), { wrapper });

    act(() =>
      result.current.mutate({ sku: 'SKU-1042', delta: 1, note: 'Cycle count' }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.stock });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.movements('SKU-1042'),
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.invariants });
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it('create invalidates stock, the order lists, the new detail and invariants', async () => {
    const { queryClient, wrapper } = setup();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    const setQueryData = vi.spyOn(queryClient, 'setQueryData');
    const { result } = renderHook(() => useCreateOrder(), { wrapper });

    act(() =>
      result.current.mutate({
        customer_ref: 'CUST-123',
        lines: [{ sku: 'SKU-1042', qty: 1 }],
      }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const order = result.current.data;
    expect(order).toBeDefined();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.stock });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['orders'] });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.order(order!.id),
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.invariants });
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it('cancel invalidates stock, the order lists, that detail and invariants', async () => {
    const { queryClient, wrapper } = setup();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    const setQueryData = vi.spyOn(queryClient, 'setQueryData');
    const { result } = renderHook(() => useCancelOrder(), { wrapper });

    act(() => result.current.mutate('ord-1001'));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.stock });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['orders'] });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.order('ord-1001'),
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.invariants });
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it('fulfil invalidates stock, the order lists, that detail and invariants', async () => {
    const { queryClient, wrapper } = setup();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    const setQueryData = vi.spyOn(queryClient, 'setQueryData');
    const { result } = renderHook(() => useFulfilOrder(), { wrapper });

    act(() => result.current.mutate('ord-1004'));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.stock });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['orders'] });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.order('ord-1004'),
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.invariants });
    expect(setQueryData).not.toHaveBeenCalled();
  });
});
