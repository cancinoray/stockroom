import { useState } from 'react';

import type { Order, OrderStatus } from '../api';
import { useCancelOrder, useFulfilOrder, useOrders } from '../api/hooks';
import { formatDateTime, formatMoney, orderNumber } from '../lib/format';
import { EmptyState } from '../components/EmptyState';
import { MovementList } from '../components/MovementList';
import { ProblemNotice } from '../components/ProblemNotice';
import { StatusPill } from '../components/StatusPill';

type OrderFilter = OrderStatus | 'all';

const FILTERS: { id: OrderFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'confirmed', label: 'Confirmed' },
  { id: 'cancelled', label: 'Cancelled' },
  { id: 'fulfilled', label: 'Fulfilled' },
];

function orderTotal(order: Order): number {
  return order.lines.reduce((total, line) => total + line.qty * line.unit_price_cents, 0);
}

export default function OrdersScreen() {
  const [filter, setFilter] = useState<OrderFilter>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  const { data, isPending, error } = useOrders(filter);
  const cancelOrder = useCancelOrder();
  const fulfilOrder = useFulfilOrder();

  const orders = data ?? [];
  const selected = orders.find((order) => order.id === selectedId) ?? orders[0] ?? null;
  const actionPending = cancelOrder.isPending || fulfilOrder.isPending;
  const actionProblem = actionError ?? cancelOrder.error ?? fulfilOrder.error;

  function selectOrder(order: Order) {
    setSelectedId(order.id);
    setActionError(null);
    cancelOrder.reset();
    fulfilOrder.reset();
  }

  function cancelSelected() {
    if (!selected) {
      return;
    }
    setActionError(null);
    cancelOrder.mutate(selected.id, { onError: setActionError });
  }

  function fulfilSelected() {
    if (!selected) {
      return;
    }
    setActionError(null);
    fulfilOrder.mutate(selected.id, { onError: setActionError });
  }

  return (
    <section>
      <header>
        <p className="eyebrow">Bay C · order desk</p>
        <h1 className="font-display text-5xl font-semibold uppercase leading-[0.9] tracking-tight sm:text-6xl">
          Orders
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-steel">
          Cancel releases the hold; fulfil moves stock off the shelf. Both write a movement, and
          neither can be undone by a second click.
        </p>
      </header>

      <div className="mt-5 flex flex-wrap gap-1" role="group" aria-label="Filter orders by status">
        {FILTERS.map((candidate) => (
          <button
            key={candidate.id}
            type="button"
            className={`btn ${filter === candidate.id ? 'border-ink bg-ink text-paper' : 'btn-ghost'}`}
            aria-pressed={filter === candidate.id}
            onClick={() => {
              setFilter(candidate.id);
              setSelectedId(null);
              setActionError(null);
            }}
          >
            {candidate.label}
          </button>
        ))}
      </div>

      {error ? (
        <div className="mt-5">
          <ProblemNotice error={error} title="Could not read orders" />
        </div>
      ) : null}

      {isPending ? <p className="mt-5 font-mono text-xs text-steel">Reading the order book…</p> : null}

      {!isPending && !error && orders.length === 0 ? (
        <div className="mt-5">
          <EmptyState
            title="No orders here"
            body="Place an order and it will appear in this lane with its full movement history."
          />
        </div>
      ) : null}

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <ul className="border border-line bg-card" aria-label="Orders">
          {orders.map((order) => {
            const current = selected?.id === order.id;
            return (
              <li key={order.id}>
                <button
                  type="button"
                  onClick={() => selectOrder(order)}
                  aria-current={current ? 'true' : undefined}
                  className={`w-full border-b border-line px-3 py-2.5 text-left transition-colors last:border-b-0 ${
                    current ? 'bg-paper' : 'hover:bg-paper/60'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs">{orderNumber(order.id)}</span>
                    <StatusPill status={order.status} />
                  </div>
                  <p className="mt-1 text-sm font-medium">{order.customer_ref}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-steel">
                    {formatDateTime(order.created_at)} · {order.lines.length} lines ·{' '}
                    {formatMoney(orderTotal(order))}
                  </p>
                </button>
              </li>
            );
          })}
        </ul>

        {selected ? (
          <article className="panel p-4">
            <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-3">
              <div>
                <p className="eyebrow">Order {orderNumber(selected.id)}</p>
                <h2 className="font-display text-3xl font-semibold uppercase leading-none">
                  {selected.customer_ref}
                </h2>
                <p className="mt-1 font-mono text-[10px] text-steel">
                  {formatDateTime(selected.created_at)}
                </p>
              </div>
              <StatusPill status={selected.status} />
            </header>

            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
              <div>
                <span className="label">Lines</span>
                <span className="font-mono text-lg">{selected.lines.length}</span>
              </div>
              <div>
                <span className="label">Total</span>
                <span className="font-mono text-lg">{formatMoney(orderTotal(selected))}</span>
              </div>
              <div>
                <span className="label">Units</span>
                <span className="font-mono text-lg">
                  {selected.lines.reduce((total, line) => total + line.qty, 0)}
                </span>
              </div>
            </div>

            <table className="mt-4 w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-line text-left">
                  <th className="py-1 font-mono text-[10px] font-normal uppercase tracking-[0.12em] text-steel">
                    SKU
                  </th>
                  <th className="py-1 text-right font-mono text-[10px] font-normal uppercase tracking-[0.12em] text-steel">
                    Qty
                  </th>
                  <th className="py-1 text-right font-mono text-[10px] font-normal uppercase tracking-[0.12em] text-steel">
                    Unit
                  </th>
                  <th className="py-1 text-right font-mono text-[10px] font-normal uppercase tracking-[0.12em] text-steel">
                    Line
                  </th>
                </tr>
              </thead>
              <tbody>
                {selected.lines.map((line) => (
                  <tr key={line.sku} className="border-b border-dashed border-line">
                    <td className="py-1.5">
                      {line.sku}
                      <span className="block font-sans text-[10px] text-steel">{line.name}</span>
                    </td>
                    <td className="py-1.5 text-right">{line.qty}</td>
                    <td className="py-1.5 text-right">{formatMoney(line.unit_price_cents)}</td>
                    <td className="py-1.5 text-right">
                      {formatMoney(line.qty * line.unit_price_cents)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
              <button
                type="button"
                className="btn btn-danger"
                onClick={cancelSelected}
                disabled={selected.status !== 'confirmed' || actionPending}
              >
                {cancelOrder.isPending ? 'Cancelling…' : 'Cancel order'}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={fulfilSelected}
                disabled={selected.status !== 'confirmed' || actionPending}
              >
                {fulfilOrder.isPending ? 'Fulfilling…' : 'Fulfil order'}
              </button>
              <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-steel">
                Only confirmed orders can move
              </span>
            </div>

            {actionProblem ? (
              <div className="mt-3">
                <ProblemNotice error={actionProblem} />
              </div>
            ) : null}

            <h3 className="mt-5 font-display text-2xl font-semibold uppercase leading-none">
              Movement timeline
            </h3>
            <MovementList
              movements={[...selected.movements].sort(
                (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
              )}
            />
          </article>
        ) : null}
      </div>
    </section>
  );
}
