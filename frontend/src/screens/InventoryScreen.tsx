import { useId, useState } from 'react';

import { isApiProblem, isValidationProblemError, type StockRow } from '../api';
import { useAdjustStock, useReceiveStock, useStock } from '../api/hooks';
import { formatMoney, formatQuantity } from '../lib/format';
import { Dialog } from '../components/Dialog';
import { EmptyState } from '../components/EmptyState';
import { MovementDrawer } from '../components/MovementDrawer';
import { ProblemNotice } from '../components/ProblemNotice';
import { StockChart } from '../components/StockChart';
import { StockTicket } from '../components/StockTicket';

type StockAction = { kind: 'receive' | 'adjust'; row: StockRow };

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'alert' }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className={`font-mono text-2xl leading-none ${tone === 'alert' ? 'text-alert' : ''}`}>
        {formatQuantity(value)}
      </dd>
    </div>
  );
}

/**
 * A 422 can carry `errors[]` with field-level messages. `ProblemNotice` owns
 * the envelope; this lists the per-field detail the operator has to fix.
 */
function ValidationErrors({ error }: { error: unknown }) {
  if (!isApiProblem(error)) {
    return null;
  }

  const entries = (error.document.errors ?? []).filter(isValidationProblemError);
  if (entries.length === 0) {
    return null;
  }

  return (
    <ul
      className="space-y-1 border border-alert/40 bg-card/60 px-3 py-2"
      aria-label="Validation errors"
    >
      {entries.map((entry, index) => (
        <li key={`${entry.field}-${index}`} className="font-mono text-[11px] text-alert">
          <span className="font-medium">{entry.field}</span>
          {entry.message ? <span>: {entry.message}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function MutationProblem({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }

  return (
    <div className="space-y-2">
      <ProblemNotice error={error} />
      <ValidationErrors error={error} />
    </div>
  );
}

function StockCounters({ row }: { row: StockRow }) {
  return (
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
  );
}

function InvalidMessage({ id, children }: { id: string; children: string }) {
  return (
    <p id={id} role="alert" className="mt-1 text-xs text-alert">
      {children}
    </p>
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

      {isPending ? <p className="mt-6 font-mono text-xs text-steel">Reading the shelf…</p> : null}

      {!isPending && !error && stock.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            title="No stock yet"
            body="Receive the first delivery to put a SKU on the shelf."
          />
        </div>
      ) : null}

      {!isPending && !error && stock.length > 0 ? <StockChart stock={stock} /> : null}

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
  const [quantityTouched, setQuantityTouched] = useState(false);
  const quantityId = useId();
  const noteId = useId();
  const quantityErrorId = useId();
  const mutation = useReceiveStock();

  const parsed = Number(quantity);
  const invalid = !Number.isInteger(parsed) || parsed <= 0;
  const showQuantityError = quantityTouched && invalid;

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
        <StockCounters row={row} />

        <div>
          <label htmlFor={quantityId} className="label mb-1">
            Quantity received
          </label>
          <input
            id={quantityId}
            className="input"
            type="number"
            min="1"
            step="1"
            value={quantity}
            aria-invalid={showQuantityError}
            aria-describedby={showQuantityError ? quantityErrorId : undefined}
            onChange={(event) => {
              setQuantity(event.target.value);
              setQuantityTouched(true);
            }}
            required
          />
          {showQuantityError ? (
            <InvalidMessage id={quantityErrorId}>
              Enter a whole number greater than zero.
            </InvalidMessage>
          ) : null}
        </div>

        <div>
          <label htmlFor={noteId} className="label mb-1">
            Note (optional)
          </label>
          <textarea
            id={noteId}
            className="textarea"
            rows={2}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Supplier, delivery reference, condition"
          />
        </div>

        <MutationProblem error={mutation.error} />

        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={invalid || mutation.isPending}
          >
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
  const [deltaTouched, setDeltaTouched] = useState(false);
  const [noteTouched, setNoteTouched] = useState(false);
  const deltaId = useId();
  const noteId = useId();
  const deltaErrorId = useId();
  const noteErrorId = useId();
  const mutation = useAdjustStock();

  const parsed = Number(delta);
  const invalid = !Number.isInteger(parsed) || parsed === 0;
  const noteMissing = note.trim().length === 0;
  const showDeltaError = deltaTouched && invalid;
  const showNoteError = noteTouched && noteMissing;

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
        <StockCounters row={row} />

        <div>
          <label htmlFor={deltaId} className="label mb-1">
            Adjustment
          </label>
          <input
            id={deltaId}
            className="input"
            type="number"
            step="1"
            value={delta}
            aria-invalid={showDeltaError}
            aria-describedby={showDeltaError ? deltaErrorId : undefined}
            onChange={(event) => {
              setDelta(event.target.value);
              setDeltaTouched(true);
            }}
            required
          />
          {showDeltaError ? (
            <InvalidMessage id={deltaErrorId}>Enter a whole number other than zero.</InvalidMessage>
          ) : (
            <span className="mt-1 block font-mono text-[10px] text-steel">
              {formatMoney(row.unit_price_cents)} per unit · negative writes stock off
            </span>
          )}
        </div>

        <div>
          <label htmlFor={noteId} className="label mb-1">
            Reason note (required)
          </label>
          <textarea
            id={noteId}
            className="textarea"
            rows={2}
            value={note}
            aria-invalid={showNoteError}
            aria-describedby={showNoteError ? noteErrorId : undefined}
            onChange={(event) => {
              setNote(event.target.value);
              setNoteTouched(true);
            }}
            placeholder="Damaged in transit, cycle count correction, return…"
            required
          />
          {showNoteError ? (
            <InvalidMessage id={noteErrorId}>
              Add a reason note so the count can be explained.
            </InvalidMessage>
          ) : null}
        </div>

        <MutationProblem error={mutation.error} />

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
