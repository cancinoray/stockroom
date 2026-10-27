import { useState } from 'react';

import type { StockRow } from '../api';
import { useAdjustStock, useReceiveStock, useStock } from '../api/hooks';
import { formatMoney, formatQuantity } from '../lib/format';
import { Dialog } from '../components/Dialog';
import { EmptyState } from '../components/EmptyState';
import { MovementDrawer } from '../components/MovementDrawer';
import { ProblemNotice } from '../components/ProblemNotice';
import { StockTicket } from '../components/StockTicket';

type StockAction = { kind: 'receive' | 'adjust'; row: StockRow };

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'alert';
}) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className={`font-mono text-2xl leading-none ${tone === 'alert' ? 'text-alert' : ''}`}>
        {formatQuantity(value)}
      </dd>
    </div>
  );
}

export default function InventoryScreen() {
  const { data, isPending, error } = useStock();
  const [ledgerSku, setLedgerSku] = useState<string | null>(null);
  const [action, setAction] = useState<StockAction | null>(null);

  const stock = data ?? [];
  const lowCount = stock.filter((row) => row.low).length;
  const availableUnits = stock.reduce((total, row) => total + row.available, 0);
  const reservedUnits = stock.reduce((total, row) => total + row.reserved, 0);

  return (
    <section>
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="eyebrow">Bay A · stock on hand</p>
          <h1 className="font-display text-5xl font-semibold uppercase leading-[0.9] tracking-tight sm:text-6xl">
            Inventory
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-steel">
            Receive deliveries and write off stock with a reason. The tally is a cache; the ledger
            is the truth.
          </p>
        </div>

        <dl className="flex gap-6">
          <Stat label="SKUs" value={stock.length} />
          <Stat label="Low" value={lowCount} tone={lowCount > 0 ? 'alert' : undefined} />
          <Stat label="Available" value={availableUnits} />
          <Stat label="Reserved" value={reservedUnits} />
        </dl>
      </header>

      {error ? (
        <div className="mt-6">
          <ProblemNotice error={error} title="Could not read stock" />
        </div>
      ) : null}

      {isPending ? (
        <p className="mt-6 font-mono text-xs text-steel">Reading the shelf…</p>
      ) : null}

      {!isPending && !error && stock.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            title="No stock yet"
            body="Receive the first delivery to put a SKU on the shelf."
          />
        </div>
      ) : null}

      <ul className="mt-6 flex flex-col gap-2" aria-label="Stock on hand">
        {stock.map((row, index) => (
          <StockTicket
            key={row.sku}
            row={row}
            index={index}
            onOpenLedger={() => setLedgerSku(row.sku)}
            onReceive={() => setAction({ kind: 'receive', row })}
            onAdjust={() => setAction({ kind: 'adjust', row })}
          />
        ))}
      </ul>

      {ledgerSku ? <MovementDrawer sku={ledgerSku} onClose={() => setLedgerSku(null)} /> : null}

      {action?.kind === 'receive' ? (
        <ReceiveDialog row={action.row} onClose={() => setAction(null)} />
      ) : null}

      {action?.kind === 'adjust' ? (
        <AdjustDialog row={action.row} onClose={() => setAction(null)} />
      ) : null}
    </section>
  );
}

function ReceiveDialog({ row, onClose }: { row: StockRow; onClose: () => void }) {
  const [quantity, setQuantity] = useState('1');
  const [note, setNote] = useState('');
  const mutation = useReceiveStock();

  const parsed = Number(quantity);
  const invalid = !Number.isInteger(parsed) || parsed <= 0;

  return (
    <Dialog title="Receive stock" eyebrow={`${row.sku} · ${row.name}`} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (invalid) {
            return;
          }
          mutation.mutate(
            { sku: row.sku, qty: parsed, note: note.trim() || undefined },
            { onSuccess: onClose },
          );
        }}
      >
        <div className="grid grid-cols-3 gap-3 border border-line bg-paper/60 p-3">
          <div>
            <span className="label">On hand</span>
            <span className="font-mono text-sm">{formatQuantity(row.on_hand)}</span>
          </div>
          <div>
            <span className="label">Reserved</span>
            <span className="font-mono text-sm">{formatQuantity(row.reserved)}</span>
          </div>
          <div>
            <span className="label">Available</span>
            <span className="font-mono text-sm">{formatQuantity(row.available)}</span>
          </div>
        </div>

        <label className="block">
          <span className="label mb-1">Quantity received</span>
          <input
            className="input"
            type="number"
            min="1"
            step="1"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            required
          />
        </label>

        <label className="block">
          <span className="label mb-1">Note (optional)</span>
          <textarea
            className="textarea"
            rows={2}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Supplier, delivery reference, condition"
          />
        </label>

        {mutation.error ? <ProblemNotice error={mutation.error} /> : null}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={invalid || mutation.isPending}>
            {mutation.isPending ? 'Receiving…' : 'Receive stock'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function AdjustDialog({ row, onClose }: { row: StockRow; onClose: () => void }) {
  const [delta, setDelta] = useState('-1');
  const [note, setNote] = useState('');
  const mutation = useAdjustStock();

  const parsed = Number(delta);
  const invalid = !Number.isInteger(parsed) || parsed === 0;
  const noteMissing = note.trim().length === 0;

  return (
    <Dialog title="Adjust stock" eyebrow={`${row.sku} · ${row.name}`} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (invalid || noteMissing) {
            return;
          }
          mutation.mutate(
            { sku: row.sku, delta: parsed, note: note.trim() },
            { onSuccess: onClose },
          );
        }}
      >
        <div className="grid grid-cols-3 gap-3 border border-line bg-paper/60 p-3">
          <div>
            <span className="label">On hand</span>
            <span className="font-mono text-sm">{formatQuantity(row.on_hand)}</span>
          </div>
          <div>
            <span className="label">Reserved</span>
            <span className="font-mono text-sm">{formatQuantity(row.reserved)}</span>
          </div>
          <div>
            <span className="label">Available</span>
            <span className="font-mono text-sm">{formatQuantity(row.available)}</span>
          </div>
        </div>

        <label className="block">
          <span className="label mb-1">Adjustment</span>
          <input
            className="input"
            type="number"
            step="1"
            value={delta}
            onChange={(event) => setDelta(event.target.value)}
            required
          />
          <span className="mt-1 block font-mono text-[10px] text-steel">
            {formatMoney(row.unit_price_cents)} per unit · negative writes stock off
          </span>
        </label>

        <label className="block">
          <span className="label mb-1">Reason note (required)</span>
          <textarea
            className="textarea"
            rows={2}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Damaged in transit, cycle count correction, return…"
            required
          />
        </label>

        {mutation.error ? <ProblemNotice error={mutation.error} /> : null}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={invalid || noteMissing || mutation.isPending}
          >
            {mutation.isPending ? 'Posting…' : 'Post adjustment'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
