import { useEffect, useId, useRef } from 'react';

import { useMovements } from '../api/hooks';
import { MovementList } from './MovementList';
import { ProblemNotice } from './ProblemNotice';

export function MovementDrawer({ sku, onClose }: { sku: string; onClose: () => void }) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const { data, isLoading, error } = useMovements(sku);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', onKeyDown);
    panelRef.current?.focus();

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-ink/45"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="h-full w-full max-w-xl overflow-y-auto border-l border-line bg-paper p-5 shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line pb-3">
          <div>
            <p className="eyebrow">Movement ledger · {sku}</p>
            <h2 id={titleId} className="font-display text-3xl font-semibold uppercase leading-none">
              Why this count?
            </h2>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close ledger">
            Close
          </button>
        </header>

        {isLoading ? <p className="mt-4 font-mono text-xs text-steel">Reading the ledger…</p> : null}
        {error ? <div className="mt-4"><ProblemNotice error={error} /></div> : null}
        {data ? <MovementList movements={data} /> : null}
      </aside>
    </div>
  );
}
