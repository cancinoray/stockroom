import { isApiProblem } from '../api';

export function ProblemNotice({ error, title }: { error: unknown; title?: string }) {
  if (!error) {
    return null;
  }

  const problem = isApiProblem(error) ? error.problem : null;
  const heading = title ?? problem?.title ?? 'Request failed';
  const detail =
    problem?.detail ?? (error instanceof Error ? error.message : 'Something went wrong.');

  return (
    <div className="notice" role="alert">
      <p className="font-semibold">{heading}</p>
      <p className="mt-1 leading-relaxed">{detail}</p>
      {problem ? (
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-steel">
          Trace {problem.trace_id} · HTTP {problem.status}
        </p>
      ) : null}
    </div>
  );
}
