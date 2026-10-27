import { useState } from 'react';

import { BayNav } from './components/BayNav';
import { Header } from './components/Header';
import InventoryScreen from './screens/InventoryScreen';
import OrdersScreen from './screens/OrdersScreen';
import PlaceOrderScreen from './screens/PlaceOrderScreen';
import type { Screen } from './lib/navigation';

export default function App() {
  const [screen, setScreen] = useState<Screen>('inventory');

  return (
    <div className="min-h-screen pb-10">
      <Header />
      <BayNav active={screen} onChange={setScreen} />

      <main className="mx-auto max-w-[1280px] px-4 pb-12 pt-6 sm:px-6">
        {screen === 'inventory' ? <InventoryScreen /> : null}
        {screen === 'place-order' ? <PlaceOrderScreen /> : null}
        {screen === 'orders' ? <OrdersScreen /> : null}
      </main>

      <footer className="mx-auto max-w-[1280px] px-4 sm:px-6">
        <p className="border-t border-line pt-4 font-mono text-[10px] uppercase tracking-[0.14em] text-steel">
          Stockroom · Main warehouse · prototype reads a mocked service layer
        </p>
      </footer>
    </div>
  );
}
