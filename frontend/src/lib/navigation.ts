export type Screen = 'inventory' | 'place-order' | 'orders';

export const BAYS: { id: Screen; letter: string; label: string }[] = [
  { id: 'inventory', letter: 'A', label: 'Inventory' },
  { id: 'place-order', letter: 'B', label: 'Place order' },
  { id: 'orders', letter: 'C', label: 'Orders' },
];
