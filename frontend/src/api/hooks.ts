import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useStockroomApi } from './context';
import type {
  AdjustInput,
  CreateOrderInput,
  OrderStatus,
  ReceiveInput,
} from './types';

export const queryKeys = {
  stock: ['stock'] as const,
  movements: (sku: string) => ['movements', sku] as const,
  orders: (status: OrderStatus | 'all') => ['orders', status] as const,
};

function invalidateInventory(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ['stock'] });
  void queryClient.invalidateQueries({ queryKey: ['movements'] });
}

export function useStock() {
  const api = useStockroomApi();
  return useQuery({ queryKey: queryKeys.stock, queryFn: () => api.listStock() });
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

export function useReceiveStock() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ReceiveInput) => api.receiveStock(input),
    onSuccess: () => invalidateInventory(queryClient),
  });
}

export function useAdjustStock() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: AdjustInput) => api.adjustStock(input),
    onSuccess: () => invalidateInventory(queryClient),
  });
}

export function useCreateOrder() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateOrderInput) => api.createOrder(input),
    onSuccess: () => {
      invalidateInventory(queryClient);
      void queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
  });
}

export function useCancelOrder() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelOrder(id),
    onSuccess: () => {
      invalidateInventory(queryClient);
      void queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
  });
}

export function useFulfilOrder() {
  const api = useStockroomApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.fulfilOrder(id),
    onSuccess: () => {
      invalidateInventory(queryClient);
      void queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
  });
}
