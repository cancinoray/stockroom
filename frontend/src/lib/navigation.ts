export type Screen = 'inventory' | 'place-order' | 'orders';

export const SCREENS: { id: Screen; label: string }[] = [
  { id: 'inventory', label: 'Inventory' },
  { id: 'place-order', label: 'Place order' },
  { id: 'orders', label: 'Orders' },
];
