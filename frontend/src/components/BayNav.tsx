import { BAYS, type Screen } from '../lib/navigation';

export function BayNav({
  active,
  onChange,
}: {
  active: Screen;
  onChange: (screen: Screen) => void;
}) {
  return (
    <nav aria-label="Stockroom bays" className="border-b border-line bg-paper">
      <div className="mx-auto flex max-w-[1280px] gap-1 overflow-x-auto px-4 sm:px-6">
        {BAYS.map((bay) => {
          const current = bay.id === active;
          return (
            <button
              key={bay.id}
              type="button"
              onClick={() => onChange(bay.id)}
              aria-current={current ? 'page' : undefined}
              className={`flex shrink-0 items-baseline gap-2 border-b-[3px] px-3 py-3 transition-colors ${
                current
                  ? 'border-signal bg-card text-ink'
                  : 'border-transparent text-steel hover:bg-card/70 hover:text-ink'
              }`}
            >
              <span className="font-mono text-[10px] uppercase tracking-[0.16em]">
                {bay.letter}
              </span>
              <span className="font-display text-lg font-semibold uppercase tracking-wide">
                {bay.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
