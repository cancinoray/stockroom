import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';

import { useStockroomApi } from './context';
import type {
  AdjustInput,
  CreateOrderInput,
  OrderStatus,
  ReceiveInput,
} from './types';

export const queryKeys = {
  products: ['products'] as const,
  stock: ['stock'] as const,
  movements: (sku: string) => ['movements', sku] as const,
  orders: (status: OrderStatus | 'all') => ['orders', status] as const,
  order: (id: string) => ['order', id] as const,
  invariants: ['invariants'] as const,
};

/**
 * A stock write changes the counters, the SKU's ledger and the invariant
 * report. Invalidate; never patch a counter locally (plan §1 guardrail 3).
 */
function invalidateStock(queryClient: QueryClient, sku?: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.stock });
  void queryClient.invalidateQueries({
    queryKey: sku ? queryKeys.movements(sku) : ['movements'],
  });
  void queryClient.invalidateQueries({ queryKey: queryKeys.invariants });
}

/** An order write changes stock, every list, that detail and the invariants. */
function invalidateOrder(queryClient: QueryClient, id: string) {
  invalidateStock(queryClient);
  void queryClient.invalidateQueries({ queryKey: ['orders'] });
  void queryClient.invalidateQueries({ queryKey: queryKeys.order(id) });
}

export function useProducts() {
  const api = useStockroomApi();
  return useQuery({
    queryKey: queryKeys.products,
    queryFn: () => api.listProducts(),
  });
}

export function useStock() {
  const api = useStockroomApi();
  return useQuery({
    queryKey: queryKeys.stock,
    queryFn: () => api.listStock(),
  });
}

export function useMovements(sku: string | null) {
  const api = useStockroomApi();
  return useQuery({
    queryKey: queryKeys.movements(sku ?? ''),
    queryFn: () => api.listMovements(sku!),
    enabled: sku !== null,
  });
}

export function useOrders(status: OrderStatus | 'all') {
  const api = useStockroomApi();
  return useQuery({
    queryKey: queryKeys.orders(status),
    queryFn: () => api.listOrders(status === 'all' ? undefined : status),
  });
}

export function useOrder(id: string | null) {
  const api = useStockroomApi();
  return useQuery({
    queryKey: queryKeys.order(id ?? ''),
    queryFn: () => api.getOrder(id!),
    enabled: id !== null,
  });
}

export function useInvariants() {
  const api = useStockroomApi();
  return useQuery({
    queryKey: queryKeys.invariants,
    queryFn: () => api.listInvariants(),
  });
}

export function useReceiveStock() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ReceiveInput) => api.receiveStock(input),
    onSuccess: (_row, input) => invalidateStock(queryClient, input.sku),
  });
}

export function useAdjustStock() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: AdjustInput) => api.adjustStock(input),
    onSuccess: (_row, input) => invalidateStock(queryClient, input.sku),
  });
}

export function useCreateOrder() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateOrderInput) => api.createOrder(input),
    onSuccess: (order) => invalidateOrder(queryClient, order.id),
  });
}

export function useCancelOrder() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelOrder(id),
    onSuccess: (order) => invalidateOrder(queryClient, order.id),
  });
}

export function useFulfilOrder() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.fulfilOrder(id),
    onSuccess: (order) => invalidateOrder(queryClient, order.id),
  });
}
