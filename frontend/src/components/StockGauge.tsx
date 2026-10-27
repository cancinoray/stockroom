import { formatQuantity } from '../lib/format';

export function StockGauge({
  onHand,
  reserved,
}: {
  onHand: number;
  reserved: number;
}) {
  const reservedShare = onHand === 0 ? 0 : Math.min(100, (reserved / onHand) * 100);

  return (
    <div
      className="gauge-track mt-1"
      role="img"
      aria-label={`${formatQuantity(onHand)} on hand, ${formatQuantity(reserved)} reserved`}
    >
      <div className="gauge-onhand" style={{ width: onHand === 0 ? 0 : '100%' }} />
      <div className="gauge-reserved" style={{ width: `${reservedShare}%` }} />
    </div>
  );
}
