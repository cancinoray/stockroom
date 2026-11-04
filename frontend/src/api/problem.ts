import {
  ApiProblem,
  type Problem,
  type ProblemError,
  type ProblemLineError,
  type ValidationProblemError,
} from './types';

export interface NormalizeContext {
  /** HTTP status from the response, when one was received. */
  status?: number;
  /** Transport-provided trace id, when the body did not carry one. */
  traceId?: string;
}

const GENERIC_DETAIL =
  'The request could not be completed. Try again, and quote the trace id if it keeps failing.';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function isStatus(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 100 &&
    value <= 599
  );
}

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

function isScalar(value: unknown): value is string | number | boolean {
  return (
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  );
}

function fallbackTraceId(): string {
  const generated = globalThis.crypto?.randomUUID?.();
  return generated ? generated.replaceAll('-', '') : 'trace-unavailable';
}

/**
 * The safe problem used for network failures, non-JSON bodies and 5xx
 * responses that did not include a problem document.
 */
export function unexpectedProblem(context: NormalizeContext = {}): Problem {
  return {
    type: 'unexpected',
    title: 'Unexpected error',
    status: isStatus(context.status) ? context.status : 500,
    detail: GENERIC_DETAIL,
    trace_id: nonEmptyString(context.traceId) ?? fallbackTraceId(),
  };
}

function normalizeLineError(entry: unknown): ProblemLineError | null {
  if (!isRecord(entry)) {
    return null;
  }

  const sku = nonEmptyString(entry.sku);
  if (sku) {
    const normalized: ProblemError = {
      sku,
      requested: isInteger(entry.requested) ? entry.requested : 0,
      available: isInteger(entry.available) ? entry.available : 0,
      short_by: isInteger(entry.short_by) ? entry.short_by : 0,
    };
    return normalized;
  }

  const field = nonEmptyString(entry.field);
  if (field) {
    const normalized: ValidationProblemError = { field };
    if (typeof entry.message === 'string') {
      normalized.message = entry.message;
    }
    if (isScalar(entry.value)) {
      normalized.value = entry.value;
    }
    return normalized;
  }

  return null;
}

/**
 * Normalize a parsed problem+json body (or a JSON string) into the generated
 * `Problem` shape, preserving `type`, `title`, `status`, `detail`, `trace_id`
 * and `errors[]`. Anything that is not a problem document becomes the safe
 * generic problem.
 */
export function normalizeProblem(
  body: unknown,
  context: NormalizeContext = {},
): Problem {
  let candidate = body;

  if (typeof candidate === 'string') {
    try {
      candidate = JSON.parse(candidate);
    } catch {
      return unexpectedProblem(context);
    }
  }

  if (!isRecord(candidate)) {
    return unexpectedProblem(context);
  }

  const type = nonEmptyString(candidate.type);
  const title = nonEmptyString(candidate.title);
  const detail = nonEmptyString(candidate.detail);

  if (!type && !title && !detail) {
    return unexpectedProblem(context);
  }

  const status = isStatus(candidate.status) ? candidate.status : undefined;
  const errors = Array.isArray(candidate.errors)
    ? candidate.errors
        .map(normalizeLineError)
        .filter((entry): entry is ProblemLineError => entry !== null)
    : undefined;

  return {
    type: type ?? 'unexpected',
    title: title ?? (type ? 'Request failed' : 'Unexpected error'),
    status: status ?? (isStatus(context.status) ? context.status : 500),
    detail: detail ?? GENERIC_DETAIL,
    trace_id:
      nonEmptyString(candidate.trace_id) ??
      nonEmptyString(context.traceId) ??
      fallbackTraceId(),
    ...(errors ? { errors } : {}),
  };
}

/**
 * Normalize any thrown value without throwing. `ApiProblem` values pass
 * through; a transport `Error` becomes the generic problem rather than leaking
 * its message into the UI.
 */
export function normalizeError(
  error: unknown,
  context: NormalizeContext = {},
): Problem {
  try {
    if (error instanceof ApiProblem) {
      return error.document;
    }
    if (error instanceof Error) {
      return unexpectedProblem(context);
    }
    return normalizeProblem(error, context);
  } catch {
    return unexpectedProblem(context);
  }
}

export function toApiProblem(
  error: unknown,
  context: NormalizeContext = {},
): ApiProblem {
  return error instanceof ApiProblem
    ? error
    : new ApiProblem(normalizeError(error, context));
}
