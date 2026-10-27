import type { OrderStatus } from '../api';

const styles: Record<OrderStatus, string> = {
  confirmed: 'border-ok text-ok',
  fulfilled: 'border-ink text-ink',
  cancelled: 'border-steel text-steel',
};

export function StatusPill({ status }: { status: OrderStatus }) {
  return (
    <span
      className={`inline-block border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em] ${styles[status]}`}
    >
      {status}
    </span>
  );
}
