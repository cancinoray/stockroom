import { useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { isApiProblem, type Movement, type Order, type OrderStatus } from '../api';
import { queryKeys, useCancelOrder, useFulfilOrder, useOrder, useOrders } from '../api/hooks';
import {
  formatDateTime,
  formatDelta,
  formatMoney,
  formatQuantity,
  orderNumber,
} from '../lib/format';
import { useModalFocus } from '../lib/useModalFocus';
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

const EMPTY_COPY: Record<OrderFilter, { title: string; body: string }> = {
  all: {
    title: 'No orders yet',
    body: 'Place an order and it will appear in this lane with its full movement history.',
  },
  confirmed: {
    title: 'No confirmed orders',
    body: 'Nothing is holding stock right now. Place an order to reserve it.',
  },
  cancelled: {
    title: 'No cancelled orders',
    body: 'Cancelling a confirmed order releases its hold and shows the release here.',
  },
  fulfilled: {
    title: 'No fulfilled orders',
    body: 'Fulfilling a confirmed order moves stock off the shelf and shows the shipment here.',
  },
};

function byNewest(a: { created_at: string }, b: { created_at: string }): number {
  return Date.parse(b.created_at) - Date.parse(a.created_at);
}

function orderTotal(order: Order): number {
  return order.lines.reduce((total, line) => total + line.qty * line.unit_price_cents, 0);
}

function orderUnits(order: Order): number {
  return order.lines.reduce((total, line) => total + line.qty, 0);
}

/**
 * The reservation behind one line: its `reserve` movement while the order is
 * confirmed, its `release` or `ship` once the order is terminal. The movements
 * arrive with the order detail, so the screen reads them instead of guessing.
 */
function lineReservation(order: Order, sku: string): Movement | null {
  return (
    order.movements
      .filter(
        (movement) =>
          movement.sku === sku &&
          (movement.reason === 'reserve' ||
            movement.reason === 'release' ||
            movement.reason === 'ship'),
      )
      .sort(byNewest)[0] ?? null
  );
}

export default function OrdersScreen() {
  const [filter, setFilter] = useState<OrderFilter>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isPending, error } = useOrders(filter);

  const orders = [...(data ?? [])].sort(byNewest);
  const empty = EMPTY_COPY[filter];

  function chooseFilter(next: OrderFilter) {
    setFilter(next);
    setSelectedId(null);
  }

  return (
    <section>
      <header>
        <h1 className="font-display text-5xl font-semibold uppercase leading-[0.9] tracking-tight sm:text-6xl">
          Orders
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-steel">
          Cancel releases the hold; fulfil moves stock off the shelf.
        </p>
      </header>

      <div className="mt-5 flex flex-wrap gap-1" role="group" aria-label="Filter orders by status">
        {FILTERS.map((candidate) => (
          <button
            key={candidate.id}
            type="button"
            className={`btn ${filter === candidate.id ? 'border-ink bg-ink text-paper' : 'btn-ghost'}`}
            aria-pressed={filter === candidate.id}
            onClick={() => chooseFilter(candidate.id)}
          >
            {candidate.label}
          </button>
        ))}
      </div>

      {error ? (
        <div className="mt-5">
          <ProblemNotice error={error} />
        </div>
      ) : null}

      {isPending ? (
        <p className="mt-5 font-mono text-xs text-steel">Reading the order book…</p>
      ) : null}

      {!isPending && !error && orders.length === 0 ? (
        <div className="mt-5">
          <EmptyState title={empty.title} body={empty.body} />
        </div>
      ) : null}

      <ul className="mt-5 border border-line bg-card" aria-label="Orders">
        {orders.map((order) => {
          const current = selectedId === order.id;
          return (
            <li key={order.id}>
              <button
                type="button"
                onClick={() => setSelectedId(order.id)}
                aria-current={current ? 'true' : undefined}
                aria-haspopup="dialog"
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

      {selectedId ? (
        <OrderDrawer
          orderId={selectedId}
          inList={orders.some((order) => order.id === selectedId)}
          onClose={() => setSelectedId(null)}
        />
      ) : null}
    </section>
  );
}

function OrderDrawer({
  orderId,
  inList,
  onClose,
}: {
  orderId: string;
  inList: boolean;
  onClose: () => void;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const { data: order, isPending, error } = useOrder(orderId);
  const cancelOrder = useCancelOrder();
  const fulfilOrder = useFulfilOrder();
  useModalFocus(panelRef, onClose);

  // A 404, or an id the lane no longer carries, is not an order to render.
  const notFound =
    (isApiProblem(error) && error.problem.status === 404) ||
    (!order && !isPending && !error && !inList);
  const actionPending = cancelOrder.isPending || fulfilOrder.isPending;
  const actionProblem = cancelOrder.error ?? fulfilOrder.error;

  /**
   * A rejected transition means this screen's copy of the order is stale, so
   * refetch the record instead of guessing what the server did.
   */
  function resync() {
    void queryClient.invalidateQueries({ queryKey: ['orders'] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.order(orderId) });
  }

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-ink/45"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="h-full w-full max-w-xl overflow-y-auto border-l border-line bg-paper p-5 shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line pb-3">
          <div>
            <p className="eyebrow">Order {orderNumber(orderId)}</p>
            <h2 id={titleId} className="font-display text-3xl font-semibold uppercase leading-none">
              {order ? order.customer_ref : 'Order detail'}
            </h2>
            {order ? (
              <p className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[10px] text-steel">
                {formatDateTime(order.created_at)}
                <StatusPill status={order.status} />
              </p>
            ) : null}
          </div>
          <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close order">
            Close
          </button>
        </header>

        {isPending ? <p className="mt-4 font-mono text-xs text-steel">Reading the order…</p> : null}

        {error ? (
          <div className="mt-4">
            <ProblemNotice error={error} />
          </div>
        ) : null}

        {notFound && !error ? (
          <div className="notice mt-4" role="alert">
            <p className="font-semibold">Order not found</p>
            <p className="mt-1 leading-relaxed">Pick another order from the lane.</p>
          </div>
        ) : null}

        {order ? (
          <>
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
              <div>
                <span className="label">Lines</span>
                <span className="font-mono text-lg">{order.lines.length}</span>
              </div>
              <div>
                <span className="label">Units</span>
                <span className="font-mono text-lg">{formatQuantity(orderUnits(order))}</span>
              </div>
              <div>
                <span className="label">Order total</span>
                <span className="font-mono text-lg">{formatMoney(orderTotal(order))}</span>
              </div>
            </div>

            <table className="mt-4 w-full font-mono text-xs">
              <caption className="sr-only">Lines, prices and reservations for this order</caption>
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
                  <th className="py-1 text-right font-mono text-[10px] font-normal uppercase tracking-[0.12em] text-steel">
                    Reservation
                  </th>
                </tr>
              </thead>
              <tbody>
                {order.lines.map((line) => {
                  const reservation = lineReservation(order, line.sku);
                  return (
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
                      <td className="py-1.5 text-right">
                        {reservation
                          ? `${reservation.reason} ${formatDelta(reservation.delta_reserved)}`
                          : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => cancelOrder.mutate(orderId, { onError: resync })}
                disabled={order.status !== 'confirmed' || actionPending}
              >
                {cancelOrder.isPending ? 'Cancelling…' : 'Cancel order'}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => fulfilOrder.mutate(orderId, { onError: resync })}
                disabled={order.status !== 'confirmed' || actionPending}
              >
                {fulfilOrder.isPending ? 'Fulfilling…' : 'Fulfil order'}
              </button>
            </div>

            {actionProblem ? (
              <div className="mt-3">
                <ProblemNotice error={actionProblem} />
              </div>
            ) : null}

            <h3 className="mt-5 font-display text-2xl font-semibold uppercase leading-none">
              Movement timeline
            </h3>
            <MovementList movements={[...order.movements].sort(byNewest)} />
          </>
        ) : null}
      </aside>
    </div>
  );
}
