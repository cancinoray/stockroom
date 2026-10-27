export function Header() {
  const today = new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date());

  return (
    <header className="border-b border-line bg-card">
      <div className="mx-auto flex max-w-[1280px] flex-wrap items-end justify-between gap-4 px-4 pb-4 pt-5 sm:px-6">
        <div className="flex items-end gap-3">
          <span className="font-display text-4xl font-bold uppercase leading-[0.85] tracking-tight sm:text-5xl">
            Stockroom
          </span>
          <span className="mb-1 border border-ink px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.18em]">
            Main
          </span>
        </div>

        <div className="text-right font-mono text-[11px] leading-relaxed text-steel">
          <p>
            Operator <span className="text-ink">demo-operator</span>
          </p>
          <p>
            Shift <span className="text-ink">{today}</span>
          </p>
        </div>
      </div>
      <div className="header-rule mx-auto h-[3px] max-w-[1280px] bg-signal" />
    </header>
  );
}
