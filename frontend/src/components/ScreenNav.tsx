import { SCREENS, type Screen } from '../lib/navigation';

export function ScreenNav({
  active,
  onChange,
}: {
  active: Screen;
  onChange: (screen: Screen) => void;
}) {
  return (
    <nav aria-label="Main navigation" className="border-b border-line bg-paper">
      <div className="mx-auto flex max-w-[1280px] gap-1 overflow-x-auto px-4 sm:px-6">
        {SCREENS.map((screen) => {
          const current = screen.id === active;
          return (
            <button
              key={screen.id}
              type="button"
              onClick={() => onChange(screen.id)}
              aria-current={current ? 'page' : undefined}
              className={`relative flex flex-1 shrink-0 items-center justify-center whitespace-nowrap px-3 py-3 font-display text-base font-semibold uppercase tracking-wide transition-colors sm:flex-none sm:px-5 sm:text-lg ${
                current
                  ? 'bg-card text-ink'
                  : 'text-steel hover:bg-card/60 hover:text-ink'
              }`}
            >
              {screen.label}
              <span
                aria-hidden="true"
                className={`absolute inset-x-2 bottom-0 h-[3px] ${
                  current ? 'bg-signal' : 'bg-transparent'
                }`}
              />
            </button>
          );
        })}
      </div>
    </nav>
  );
}
