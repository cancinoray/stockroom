export function formatMoney(cents: number): string {
  return new Intl.NumberFormat('en-PH', {
    style: 'currency',
    currency: 'PHP',
    minimumFractionDigits: 2,
  }).format(cents / 100);
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat('en-PH', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso));
}

export function formatShortDate(iso: string): string {
  return new Intl.DateTimeFormat('en-PH', {
    month: 'short',
    day: '2-digit',
  }).format(new Date(iso));
}

export function formatQuantity(value: number): string {
  return new Intl.NumberFormat('en-PH').format(value);
}

export function formatDelta(value: number): string {
  if (value === 0) {
    return '—';
  }
  return `${value > 0 ? '+' : ''}${formatQuantity(value)}`;
}

export function orderNumber(id: string): string {
  return `#${id.replace(/^ord-/, '')}`;
}
