import type { StockRow } from '../api';
import { formatQuantity } from '../lib/format';

export function StockChart({ stock }: { stock: StockRow[] }) {
  const maxOnHand = Math.max(...stock.map((row) => row.on_hand), 1);
  const rows = [...stock].sort(
    (a, b) => a.available - b.available || a.sku.localeCompare(b.sku),
  );

  return (
    <section
      aria-labelledby="stock-chart-title"
      className="panel mt-6 p-4"
    >
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
        <div>
          <p className="eyebrow">Shelf position · lowest available first</p>
          <h2
            id="stock-chart-title"
            className="font-display text-2xl font-semibold uppercase leading-none"
          >
            Stock on hand
          </h2>
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-[0.12em] text-steel">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 bg-ink" aria-hidden="true" /> Available
          </span>
          <span className="flex items-center gap-1.5">
            <span className="swatch-reserved h-2.5 w-4" aria-hidden="true" /> Reserved
          </span>
          <span>Bar = on hand</span>
        </div>
      </div>

      <ul className="mt-3 grid gap-x-6 gap-y-2.5 md:grid-cols-2">
        {rows.map((row) => {
          const onHandWidth = (row.on_hand / maxOnHand) * 100;
          const reservedShare = row.on_hand === 0 ? 0 : (row.reserved / row.on_hand) * 100;

          return (
            <li key={row.sku}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5 font-mono text-[10px]">
                <span className={row.low ? 'text-alert' : ''}>
                  {row.sku}
                  {row.low ? ' · LOW' : ''}
                </span>
                <span className="text-steel">
                  {formatQuantity(row.on_hand)} on hand · {formatQuantity(row.reserved)} reserved ·{' '}
                  {formatQuantity(row.available)} available
                </span>
              </div>

              <div
                className={`relative mt-1 h-3.5 overflow-hidden bg-line/70 ${
                  row.low ? 'outline outline-1 outline-alert/50' : ''
                }`}
                aria-hidden="true"
              >
                <div
                  className="absolute inset-y-0 left-0 bg-ink"
                  style={{ width: `${onHandWidth}%` }}
                >
                  <div
                    className="gauge-reserved absolute inset-y-0 right-0"
                    style={{ width: `${reservedShare}%` }}
                  />
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="mt-3 font-mono text-[10px] text-steel">
        Scale: {formatQuantity(maxOnHand)} units. Reserved stock is part of on-hand; the unhatched
        ink is available.
      </p>
    </section>
  );
}
