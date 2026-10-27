export type OrderStatus = 'confirmed' | 'cancelled' | 'fulfilled';

export type MovementReason = 'receive' | 'adjust' | 'reserve' | 'release' | 'ship';

export interface StockRow {
  sku: string;
  name: string;
  on_hand: number;
  reserved: number;
  available: number;
  reorder_point: number;
  unit_price_cents: number;
  low: boolean;
}

export interface Movement {
  id: string;
  sku: string;
  reason: MovementReason;
  delta_on_hand: number;
  delta_reserved: number;
  actor: string;
  note: string | null;
  order_id: string | null;
  created_at: string;
  on_hand_after: number;
}

export interface OrderLine {
  sku: string;
  name: string;
  qty: number;
  unit_price_cents: number;
}

export interface Order {
  id: string;
  customer_ref: string;
  status: OrderStatus;
  created_at: string;
  lines: OrderLine[];
  movements: Movement[];
}

export interface ProblemError {
  sku: string;
  requested: number;
  available: number;
  short_by: number;
}

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  trace_id: string;
  errors?: ProblemError[];
}

export interface ReceiveInput {
  sku: string;
  qty: number;
  note?: string;
}

export interface AdjustInput {
  sku: string;
  delta: number;
  note: string;
}

export interface CreateOrderInput {
  customer_ref: string;
  lines: { sku: string; qty: number }[];
}

export interface StockroomApi {
  listStock(): Promise<StockRow[]>;
  listMovements(sku: string): Promise<Movement[]>;
  receiveStock(input: ReceiveInput): Promise<StockRow>;
  adjustStock(input: AdjustInput): Promise<StockRow>;
  listOrders(status?: OrderStatus): Promise<Order[]>;
  createOrder(input: CreateOrderInput): Promise<Order>;
  cancelOrder(id: string): Promise<Order>;
  fulfilOrder(id: string): Promise<Order>;
}

export class ApiProblem extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail);
    this.name = 'ApiProblem';
    this.problem = problem;
  }
}

export function isApiProblem(error: unknown): error is ApiProblem {
  return error instanceof ApiProblem;
}
