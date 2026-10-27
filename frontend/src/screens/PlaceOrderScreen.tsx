import { useState, type FormEvent } from 'react';

import { isApiProblem, type Order, type ProblemError } from '../api';
import { useCreateOrder, useStock } from '../api/hooks';
import { formatMoney, formatQuantity, orderNumber } from '../lib/format';
import { EmptyState } from '../components/EmptyState';
import { ProblemNotice } from '../components/ProblemNotice';

interface TicketLine {
  sku: string;
  qty: number;
}

export default function PlaceOrderScreen() {
  const { data, isPending, error } = useStock();
  const createOrder = useCreateOrder();

  const [search, setSearch] = useState('');
  const [customerRef, setCustomerRef] = useState('');
  const [lines, setLines] = useState<TicketLine[]>([]);
  const [confirmation, setConfirmation] = useState<Order | null>(null);

  const stock = data ?? [];
  const query = search.trim().toLowerCase();
  const filtered = query
    ? stock.filter(
        (row) => row.sku.toLowerCase().includes(query) || row.name.toLowerCase().includes(query),
      )
    : stock;

  const shortBySku = new Map<string, ProblemError>();
  if (isApiProblem(createOrder.error)) {
    for (const shortLine of createOrder.error.problem.errors ?? []) {
      shortBySku.set(shortLine.sku, shortLine);
    }
  }

  const totalCents = lines.reduce((total, line) => {
    const row = stock.find((candidate) => candidate.sku === line.sku);
    return total + (row ? row.unit_price_cents * line.qty : 0);
  }, 0);

  const refLength = customerRef.trim().length;
  const hasInvalidQuantity = lines.some(
    (line) => !Number.isInteger(line.qty) || line.qty <= 0,
  );
  const canSubmit =
    lines.length > 0 &&
    !hasInvalidQuantity &&
    refLength >= 3 &&
    refLength <= 40 &&
    !createOrder.isPending;

  function addLine(sku: string) {
    createOrder.reset();
    setConfirmation(null);
    setLines((current) => {
      const existing = current.find((line) => line.sku === sku);
      if (existing) {
        return current.map((line) =>
          line.sku === sku ? { ...line, qty: line.qty + 1 } : line,
        );
      }
      return [...current, { sku, qty: 1 }];
    });
  }

  function setQuantity(sku: string, qty: number) {
    createOrder.reset();
    setLines((current) =>
      current.map((line) => (line.sku === sku ? { ...line, qty } : line)),
    );
  }

  function removeLine(sku: string) {
    createOrder.reset();
    setLines((current) => current.filter((line) => line.sku !== sku));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    createOrder.mutate(
      {
        customer_ref: customerRef.trim(),
        lines: lines.map((line) => ({ sku: line.sku, qty: line.qty })),
      },
      {
        onSuccess: (order) => {
          setConfirmation(order);
          setLines([]);
          setCustomerRef('');
        },
      },
    );
  }

  return (
    <section>
      <header>
        <p className="eyebrow">Bay B · promise stock</p>
        <h1 className="font-display text-5xl font-semibold uppercase leading-[0.9] tracking-tight sm:text-6xl">
          Place order
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-steel">
          An order reserves every line or reserves nothing. Short lines come back named, so the
          customer hears the real answer.
        </p>
      </header>

      {error ? (
        <div className="mt-6">
          <ProblemNotice error={error} title="Could not read stock" />
        </div>
      ) : null}

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)]">
        <div>
          <div className="flex items-end justify-between gap-3">
            <label className="block w-full">
              <span className="label mb-1">Search stock</span>
              <input
                className="input"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="SKU or item name"
                aria-label="Search stock"
              />
            </label>
            <span className="shrink-0 whitespace-nowrap pb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-steel">
              {filtered.length} shown
            </span>
          </div>

          {isPending ? (
            <p className="mt-4 font-mono text-xs text-steel">Reading the shelf…</p>
          ) : null}

          {!isPending && filtered.length === 0 ? (
            <div className="mt-4">
              <EmptyState
                title="No match"
                body="Try a different SKU or part of the item name."
              />
            </div>
          ) : null}

          <ul className="mt-4 border border-line bg-card" aria-label="Stock available to order">
            {filtered.map((row) => (
              <li
                key={row.sku}
                className="flex items-center gap-3 border-b border-line p-3 last:border-b-0"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-xs">{row.sku}</p>
                  <p className="truncate text-sm text-steel">{row.name}</p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-sm">{formatQuantity(row.available)}</p>
                  <p className="label">available</p>
                </div>
                <button
                  type="button"
                  className="btn"
                  onClick={() => addLine(row.sku)}
                  disabled={row.available === 0}
                  aria-label={`Add ${row.sku}`}
                >
                  Add
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div>
          {confirmation ? (
            <div className="notice-ok mb-4" role="status">
              <p className="font-semibold">
                Order {orderNumber(confirmation.id)} confirmed for {confirmation.customer_ref}.
              </p>
              <p className="mt-1">
                {confirmation.lines.length} lines reserved ·{' '}
                {formatMoney(
                  confirmation.lines.reduce(
                    (total, line) => total + line.qty * line.unit_price_cents,
                    0,
                  ),
                )}
              </p>
            </div>
          ) : null}

          <form className="panel p-4" onSubmit={submit}>
            <div className="flex items-baseline justify-between gap-3 border-b border-line pb-2">
              <h2 className="font-display text-2xl font-semibold uppercase leading-none">
                Order ticket
              </h2>
              <span className="eyebrow">All or nothing</span>
            </div>

            <label className="mt-3 block">
              <span className="label mb-1">Customer reference</span>
              <input
                className="input"
                value={customerRef}
                onChange={(event) => {
                  createOrder.reset();
                  setCustomerRef(event.target.value);
                }}
                placeholder="CUST-88"
                aria-label="Customer reference"
                required
              />
              <span className="mt-1 block font-mono text-[10px] text-steel">
                3–40 characters. A reference, not a customer name.
              </span>
            </label>

            {lines.length === 0 ? (
              <p className="mt-5 border border-dashed border-line p-4 text-sm text-steel">
                No lines yet. Add stock from the shelf list.
              </p>
            ) : (
              <ul className="mt-4" aria-label="Order lines">
                {lines.map((line) => {
                  const row = stock.find((candidate) => candidate.sku === line.sku);
                  const shortLine = shortBySku.get(line.sku);
                  const invalidQuantity = !Number.isInteger(line.qty) || line.qty <= 0;
                  return (
                    <li key={line.sku} className="ledger-row py-2.5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="font-mono text-xs">{line.sku}</p>
                          <p className="truncate text-xs text-steel">{row?.name}</p>
                        </div>
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => removeLine(line.sku)}
                          aria-label={`Remove ${line.sku}`}
                        >
                          Remove
                        </button>
                      </div>
                      <div className="mt-2 flex items-end justify-between gap-3">
                        <label className="w-24">
                          <span className="label mb-1">Qty</span>
                          <input
                            className={`input ${invalidQuantity ? 'border-alert' : ''}`}
                            type="number"
                            min="1"
                            step="1"
                            value={line.qty}
                            onChange={(event) =>
                              setQuantity(line.sku, Number(event.target.value))
                            }
                            aria-label={`Quantity for ${line.sku}`}
                            aria-invalid={invalidQuantity || undefined}
                          />
                        </label>
                        <p className="font-mono text-xs">
                          {row ? formatMoney(row.unit_price_cents * line.qty) : '—'}
                        </p>
                      </div>
                      {invalidQuantity ? (
                        <p className="mt-1 font-mono text-[10px] text-alert">
                          Enter a whole number greater than zero.
                        </p>
                      ) : null}
                      {shortLine ? (
                        <p className="mt-1 font-mono text-[10px] text-alert">
                          Available {formatQuantity(shortLine.available)} · short by{' '}
                          {formatQuantity(shortLine.short_by)}
                        </p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}

            <div className="mt-4 flex items-baseline justify-between border-t border-line pt-3">
              <span className="eyebrow">Order total</span>
              <span className="font-mono text-xl">{formatMoney(totalCents)}</span>
            </div>

            {createOrder.error ? (
              <div className="mt-3">
                <ProblemNotice error={createOrder.error} />
              </div>
            ) : null}

            <button
              type="submit"
              className="btn btn-primary mt-4 w-full"
              disabled={!canSubmit}
            >
              {createOrder.isPending ? 'Reserving…' : 'Reserve stock'}
            </button>
            <p className="mt-2 text-center font-mono text-[10px] uppercase tracking-[0.12em] text-steel">
              If one line is short, nothing is reserved
            </p>
          </form>
        </div>
      </div>
    </section>
  );
}
