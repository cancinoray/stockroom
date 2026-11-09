import { useState } from 'react';

import { ScreenNav } from './components/ScreenNav';
import { Header } from './components/Header';
import InventoryScreen from './screens/InventoryScreen';
import OrdersScreen from './screens/OrdersScreen';
import PlaceOrderScreen from './screens/PlaceOrderScreen';
import type { Screen } from './lib/navigation';

export default function App() {
  const [screen, setScreen] = useState<Screen>('inventory');

  return (
    <div className="min-h-screen">
      <Header />
      <ScreenNav active={screen} onChange={setScreen} />

      <main className="mx-auto max-w-[1280px] px-4 pb-12 pt-6 sm:px-6">
        {screen === 'inventory' ? <InventoryScreen /> : null}
        {screen === 'place-order' ? <PlaceOrderScreen /> : null}
        {screen === 'orders' ? <OrdersScreen /> : null}
      </main>

    </div>
  );
}
