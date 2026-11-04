import type { components } from './schema';

/**
 * The generated contract types. Every entity shape in this file is an alias of
 * `components['schemas']`; nothing below hand-writes a response shape.
 */
export type API = components['schemas'];

export type OrderStatus = API['OrderStatus'];
export type MovementReason = API['MovementReason'];
export type StockRow = API['StockRow'];
export type Movement = API['Movement'];
export type OrderLine = API['OrderLine'];
export type Order = API['Order'];
export type Product = API['Product'];
export type ProblemError = API['ProblemError'];
export type ValidationProblemError = API['ValidationProblemError'];
export type ProblemLineError = NonNullable<API['Problem']['errors']>[number];
export type Problem = API['Problem'];
/**
 * The legacy consumer view: existing screens read `problem.errors` as the
 * short-line entries only. The full normalized document (including validation
 * entries) is preserved on `ApiProblem.document`.
 */
export type ProblemView = Omit<API['Problem'], 'errors'> & {
  errors?: ProblemError[];
};
export type InvariantViolation = API['InvariantViolation'];
export type InvariantReport = API['InvariantReport'];

export type ReceiveInput = API['ReceiveRequest'];
export type AdjustInput = API['AdjustRequest'];
export type CreateOrderInput = API['CreateOrderRequest'];

/**
 * A short-line error names the SKU; a validation error names the field. The
 * generated `Problem.errors` is a union of both, so the guards below narrow it
 * without a cast at every call site.
 */
export function isProblemError(error: ProblemLineError): error is ProblemError {
  return 'sku' in error;
}

export function isValidationProblemError(
  error: ProblemLineError,
): error is ValidationProblemError {
  return 'field' in error;
}

/**
 * Behavior surface implemented by both the mock and the real HTTP client.
 * Types are generated from `openapi.yaml`; the calls themselves are hand-built.
 */
export interface StockroomApi {
  listProducts(): Promise<Product[]>;
  listStock(): Promise<StockRow[]>;
  listMovements(sku: string): Promise<Movement[]>;
  receiveStock(input: ReceiveInput): Promise<StockRow>;
  adjustStock(input: AdjustInput): Promise<StockRow>;
  listOrders(status?: OrderStatus): Promise<Order[]>;
  getOrder(id: string): Promise<Order>;
  createOrder(input: CreateOrderInput): Promise<Order>;
  cancelOrder(id: string): Promise<Order>;
  fulfilOrder(id: string): Promise<Order>;
  listInvariants(): Promise<InvariantReport>;
}

export class ApiProblem extends Error {
  /** The full normalized problem document, including validation entries. */
  readonly document: Problem;
  /** The short-line view existing screens already consume. */
  readonly problem: ProblemView;

  constructor(document: Problem) {
    super(document.detail);
    this.name = 'ApiProblem';
    this.document = document;
    this.problem = toProblemView(document);
  }
}

function toProblemView(document: Problem): ProblemView {
  const errors = document.errors?.filter(isProblemError);

  return {
    type: document.type,
    title: document.title,
    status: document.status,
    detail: document.detail,
    trace_id: document.trace_id,
    ...(errors && errors.length > 0 ? { errors } : {}),
  };
}

export function isApiProblem(error: unknown): error is ApiProblem {
  return error instanceof ApiProblem;
}
