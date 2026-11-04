import { describe, expect, it } from 'vitest';

import { normalizeError, normalizeProblem, toApiProblem } from './problem';
import {
  isApiProblem,
  isProblemError,
  isValidationProblemError,
} from './types';

const insufficientStock = {
  type: 'insufficient_stock',
  title: 'Not enough stock',
  status: 409,
  detail: 'SKU-B is short. No stock was reserved.',
  trace_id: 'trace-abc-123',
  errors: [{ sku: 'SKU-B', requested: 5, available: 2, short_by: 3 }],
};

describe('problem normalization', () => {
  it('preserves every field of a problem+json body including per-line errors', () => {
    const problem = normalizeProblem(insufficientStock);

    expect(problem).toEqual(insufficientStock);
  });

  it('preserves field-level validation entries and distinguishes them without a cast', () => {
    const problem = normalizeProblem({
      type: 'validation_error',
      title: 'Invalid quantity',
      status: 422,
      detail: 'Quantity must be a whole number greater than zero.',
      trace_id: 'trace-422',
      errors: [
        {
          field: 'lines.0.qty',
          message: 'Input should be a valid integer',
          value: 'many',
        },
      ],
    });

    const errors = problem.errors ?? [];
    expect(errors).toHaveLength(1);

    const [entry] = errors;
    if (!isValidationProblemError(entry)) {
      throw new Error('expected a ValidationProblemError');
    }
    expect(entry.field).toBe('lines.0.qty');
    expect(entry.message).toBe('Input should be a valid integer');
    expect(entry.value).toBe('many');
    expect(isProblemError(entry)).toBe(false);
  });

  it('distinguishes a short-line ProblemError from a ValidationProblemError', () => {
    const problem = normalizeProblem(insufficientStock);
    const [entry] = problem.errors ?? [];

    if (!isProblemError(entry)) {
      throw new Error('expected a ProblemError');
    }
    expect(entry).toMatchObject({
      sku: 'SKU-B',
      requested: 5,
      available: 2,
      short_by: 3,
    });
    expect(isValidationProblemError(entry)).toBe(false);
  });

  it('parses a JSON string body from a non-standard content type', () => {
    const problem = normalizeProblem(JSON.stringify(insufficientStock));

    expect(problem.type).toBe('insufficient_stock');
    expect(problem.trace_id).toBe('trace-abc-123');
  });

  it('normalizes a non-JSON body to a generic problem', () => {
    const problem = normalizeError('<html>bad gateway</html>', { status: 502 });

    expect(problem.type).toBe('unexpected');
    expect(problem.status).toBe(502);
    expect(problem.title.length).toBeGreaterThan(0);
    expect(problem.detail.length).toBeGreaterThan(0);
    expect(problem.trace_id.length).toBeGreaterThan(0);
  });

  it('normalizes a network failure to a generic problem', () => {
    const problem = normalizeError(new TypeError('Failed to fetch'));

    expect(problem.type).toBe('unexpected');
    expect(problem.status).toBe(500);
    expect(problem.title.length).toBeGreaterThan(0);
    expect(problem.detail.length).toBeGreaterThan(0);
    expect(problem.trace_id.length).toBeGreaterThan(0);
  });

  it('normalizes a 5xx without a problem body to a generic problem', () => {
    const problem = normalizeError(undefined, { status: 503 });

    expect(problem.type).toBe('unexpected');
    expect(problem.status).toBe(503);
    expect(problem.title.length).toBeGreaterThan(0);
    expect(problem.detail.length).toBeGreaterThan(0);
    expect(problem.trace_id.length).toBeGreaterThan(0);
  });

  it('fills a missing trace id and never throws for hostile input', () => {
    const hostile: unknown[] = [
      null,
      undefined,
      42,
      [],
      { errors: 'not-an-array' },
      { type: '', title: '', status: 999, detail: '', trace_id: '' },
      Symbol('nope'),
    ];

    for (const value of hostile) {
      let problem: ReturnType<typeof normalizeError> | undefined;
      expect(() => {
        problem = normalizeError(value);
      }).not.toThrow();
      expect(problem?.type.length).toBeGreaterThan(0);
      expect(problem?.title.length).toBeGreaterThan(0);
      expect(problem?.detail.length).toBeGreaterThan(0);
      expect(problem?.trace_id.length).toBeGreaterThan(0);
    }
  });

  it('wraps a normalized problem in the ApiProblem the existing consumers expect', () => {
    const wrapped = toApiProblem(insufficientStock);

    expect(isApiProblem(wrapped)).toBe(true);
    expect(wrapped.problem).toEqual(insufficientStock);
    expect(wrapped.document).toEqual(insufficientStock);
    expect(wrapped.message).toBe(insufficientStock.detail);
  });

  it('keeps validation entries on the document without widening the legacy view', () => {
    const wrapped = toApiProblem({
      type: 'validation_error',
      title: 'Invalid quantity',
      status: 422,
      detail: 'Quantity must be a whole number greater than zero.',
      trace_id: 'trace-422',
      errors: [
        {
          field: 'lines.0.qty',
          message: 'Input should be a valid integer',
          value: 'many',
        },
      ],
    });

    const [entry] = wrapped.document.errors ?? [];
    if (!isValidationProblemError(entry)) {
      throw new Error('expected a ValidationProblemError on the document');
    }
    expect(entry.field).toBe('lines.0.qty');
    expect(wrapped.problem.errors ?? []).toHaveLength(0);
  });
});
