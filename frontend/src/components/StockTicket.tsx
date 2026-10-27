import type { StockRow } from '../api';
import { formatMoney, formatQuantity } from '../lib/format';
import { StockGauge } from './StockGauge';

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'signal' | 'alert';
}) {
  const color = tone === 'alert' ? 'text-alert' : tone === 'signal' ? 'text-signal' : 'text-ink';

  return (
    <div>
      <span className="label">{label}</span>
      <span className={`block font-mono text-lg leading-tight ${color}`}>{value}</span>
    </div>
  );
}

export function StockTicket({
  row,
  index,
  onOpenLedger,
  onReceive,
  onAdjust,
}: {
  row: StockRow;
  index: number;
  onOpenLedger: () => void;
  onReceive: () => void;
  onAdjust: () => void;
}) {
  return (
    <li
      className="bin-ticket reveal relative pl-6"
      style={{ animationDelay: `${Math.min(index, 8) * 30}ms` }}
    >
      {row.low ? (
        <span className="hazard-edge absolute inset-y-0 left-0 w-2" aria-hidden="true" />
      ) : null}

      <div className="grid grid-cols-2 gap-x-4 gap-y-3 p-4 md:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,0.55fr))_minmax(0,0.9fr)_auto] md:items-center">
        <div className="col-span-2 min-w-0 md:col-span-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-medium tracking-wide">{row.sku}</span>
            {row.low ? <span className="stamp">Low</span> : null}
          </div>
          <p className="truncate text-sm text-steel">{row.name}</p>
        </div>

        <Metric label="On hand" value={formatQuantity(row.on_hand)} />
        <Metric
          label="Reserved"
          value={formatQuantity(row.reserved)}
          tone={row.reserved > 0 ? 'signal' : undefined}
        />
        <Metric
          label="Available"
          value={formatQuantity(row.available)}
          tone={row.available === 0 ? 'alert' : undefined}
        />

        <div className="col-span-2 md:col-span-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="label">Reorder at</span>
            <span className="font-mono text-xs">{formatQuantity(row.reorder_point)}</span>
          </div>
          <StockGauge onHand={row.on_hand} reserved={row.reserved} />
          <p className="mt-1 font-mono text-[10px] text-steel">
            {formatMoney(row.unit_price_cents)} each
          </p>
        </div>

        <div className="col-span-2 flex flex-wrap gap-1.5 md:col-span-1 md:justify-end">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onOpenLedger}
            aria-label={`Movement history for ${row.sku}`}
          >
            History
          </button>
          <button type="button" className="btn" onClick={onReceive}>
            Receive
          </button>
          <button type="button" className="btn" onClick={onAdjust}>
            Adjust
          </button>
        </div>
      </div>
    </li>
  );
}
