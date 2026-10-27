import { createContext, useContext, type ReactNode } from 'react';

import type { StockroomApi } from './types';

const StockroomApiContext = createContext<StockroomApi | null>(null);

export function StockroomApiProvider({
  api,
  children,
}: {
  api: StockroomApi;
  children: ReactNode;
}) {
  return <StockroomApiContext.Provider value={api}>{children}</StockroomApiContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useStockroomApi(): StockroomApi {
  const api = useContext(StockroomApiContext);
  if (!api) {
    throw new Error('useStockroomApi must be used inside StockroomApiProvider');
  }
  return api;
}
