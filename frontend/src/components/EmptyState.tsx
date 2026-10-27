import type { ReactNode } from 'react';

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="border border-dashed border-line bg-card/60 p-8 text-center">
      <p className="font-display text-2xl font-semibold uppercase">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm leading-relaxed text-steel">{body}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
