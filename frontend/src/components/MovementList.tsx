import type { Movement } from '../api';
import { formatDateTime, formatDelta, formatQuantity } from '../lib/format';

export function MovementList({ movements }: { movements: Movement[] }) {
  if (movements.length === 0) {
    return <p className="mt-3 font-mono text-xs text-steel">No movements recorded yet.</p>;
  }

  return (
    <div className="mt-3">
      <div className="hidden grid-cols-[7.5rem_minmax(0,1fr)_3.5rem_3.5rem_3.5rem] gap-2 py-1 sm:grid">
        <span className="label">When</span>
        <span className="label">Reason / note</span>
        <span className="label text-right">On hand</span>
        <span className="label text-right">Reserved</span>
        <span className="label text-right">Balance</span>
      </div>
      <ol aria-label="Movement ledger">
        {movements.map((movement) => (
          <li key={movement.id} className="ledger-row py-2 font-mono text-[11px]">
            <div className="grid gap-1 sm:grid-cols-[7.5rem_minmax(0,1fr)_3.5rem_3.5rem_3.5rem] sm:items-baseline sm:gap-2">
              <span className="text-steel">{formatDateTime(movement.created_at)}</span>
              <span className="min-w-0">
                <span className="uppercase tracking-[0.08em]">{movement.reason}</span>
                {movement.note ? <span className="text-steel"> · {movement.note}</span> : null}
                <span className="block text-[10px] text-steel">
                  {movement.actor}
                  {movement.order_id ? ` · #${movement.order_id.replace(/^ord-/, '')}` : ''}
                </span>
              </span>
              <div className="grid grid-cols-3 gap-2 sm:contents">
                <span className="sm:text-right">
                  <span className="text-steel sm:hidden">On hand </span>
                  {formatDelta(movement.delta_on_hand)}
                </span>
                <span className="sm:text-right">
                  <span className="text-steel sm:hidden">Reserved </span>
                  {formatDelta(movement.delta_reserved)}
                </span>
                <span className="sm:text-right">
                  <span className="text-steel sm:hidden">Balance </span>
                  {formatQuantity(movement.on_hand_after)}
                </span>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
