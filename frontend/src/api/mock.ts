import {
  ApiProblem,
  type AdjustInput,
  type CreateOrderInput,
  type Movement,
  type MovementReason,
  type Order,
  type OrderLine,
  type OrderStatus,
  type Problem,
  type ProblemError,
  type ReceiveInput,
  type StockRow,
  type StockroomApi,
} from './types';

interface SeedProduct {
  sku: string;
  name: string;
  opening: number;
  reorder_point: number;
  unit_price_cents: number;
}

interface StockCounters {
  on_hand: number;
  reserved: number;
}

export interface MockApiOptions {
  latencyMs?: number;
}

const SEED_PRODUCTS: SeedProduct[] = [
  {
    sku: 'SKU-1042',
    name: 'Desk lamp, matte black',
    opening: 18,
    reorder_point: 6,
    unit_price_cents: 129_900,
  },
  {
    sku: 'SKU-2087',
    name: 'Task chair, graphite',
    opening: 10,
    reorder_point: 4,
    unit_price_cents: 899_900,
  },
  {
    sku: 'SKU-3301',
    name: 'A4 copy paper, 500 sheets',
    opening: 40,
    reorder_point: 20,
    unit_price_cents: 28_900,
  },
  {
    sku: 'SKU-4410',
    name: 'Monitor arm, single',
    opening: 5,
    reorder_point: 3,
    unit_price_cents: 349_900,
  },
  {
    sku: 'SKU-5127',
    name: 'Cable tray, 1 metre',
    opening: 6,
    reorder_point: 10,
    unit_price_cents: 74_900,
  },
  {
    sku: 'SKU-6093',
    name: 'Storage bin, 15 litre',
    opening: 27,
    reorder_point: 8,
    unit_price_cents: 45_900,
  },
  {
    sku: 'SKU-7714',
    name: 'Packing tape, 50 metre',
    opening: 12,
    reorder_point: 14,
    unit_price_cents: 12_900,
  },
  {
    sku: 'SKU-8820',
    name: 'Label printer, thermal',
    opening: 3,
    reorder_point: 2,
    unit_price_cents: 1_249_900,
  },
];

const OPENING_AT = '2026-10-21T08:00:00Z';

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function addHours(iso: string, hours: number): string {
  return new Date(Date.parse(iso) + hours * 3_600_000).toISOString();
}

export function createMockApi({ latencyMs = 250 }: MockApiOptions = {}): StockroomApi {
  const products = new Map(SEED_PRODUCTS.map((product) => [product.sku, product]));
  const stock = new Map<string, StockCounters>(
    SEED_PRODUCTS.map((product) => [product.sku, { on_hand: 0, reserved: 0 }]),
  );
  const movements: Movement[] = [];
  const orders: Order[] = [];

  let orderSequence = 1006;
  let movementSequence = 1;
  let traceSequence = 1;

  function wait(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, latencyMs));
  }

  function makeProblem(
    type: string,
    title: string,
    status: number,
    detail: string,
    errors?: ProblemError[],
  ): Problem {
    return { type, title, status, detail, trace_id: `mock-${traceSequence++}`, errors };
  }

  function fail(
    type: string,
    title: string,
    status: number,
    detail: string,
    errors?: ProblemError[],
  ): never {
    throw new ApiProblem(makeProblem(type, title, status, detail, errors));
  }

  function counters(sku: string): StockCounters {
    const row = stock.get(sku);
    if (!row) {
      fail('not_found', 'Not found', 404, `SKU ${sku} does not exist.`);
    }
    return row;
  }

  function product(sku: string): SeedProduct {
    const row = products.get(sku);
    if (!row) {
      fail('not_found', 'Not found', 404, `SKU ${sku} does not exist.`);
    }
    return row;
  }

  function recordMovement(input: {
    sku: string;
    reason: MovementReason;
    delta_on_hand: number;
    delta_reserved: number;
    actor: string;
    note: string | null;
    order_id: string | null;
    created_at: string;
  }): Movement {
    const current = counters(input.sku);
    current.on_hand += input.delta_on_hand;
    current.reserved += input.delta_reserved;

    const movement: Movement = {
      id: `mv-${movementSequence++}`,
      sku: input.sku,
      reason: input.reason,
      delta_on_hand: input.delta_on_hand,
      delta_reserved: input.delta_reserved,
      actor: input.actor,
      note: input.note,
      order_id: input.order_id,
      created_at: input.created_at,
      on_hand_after: current.on_hand,
    };
    movements.push(movement);
    return movement;
  }

  function toStockRow(sku: string): StockRow {
    const seed = product(sku);
    const current = counters(sku);
    const available = current.on_hand - current.reserved;

    return {
      sku: seed.sku,
      name: seed.name,
      on_hand: current.on_hand,
      reserved: current.reserved,
      available,
      reorder_point: seed.reorder_point,
      unit_price_cents: seed.unit_price_cents,
      low: available <= seed.reorder_point,
    };
  }

  function byNewest(a: { created_at: string }, b: { created_at: string }): number {
    return Date.parse(b.created_at) - Date.parse(a.created_at);
  }

  function seedOrder(input: {
    id: string;
    customer_ref: string;
    status: OrderStatus;
    created_at: string;
    lines: { sku: string; qty: number }[];
  }): void {
    const lines: OrderLine[] = input.lines.map((line) => {
      const seed = products.get(line.sku);
      if (!seed) {
        throw new Error(`Seed order references unknown SKU ${line.sku}`);
      }
      return {
        sku: seed.sku,
        name: seed.name,
        qty: line.qty,
        unit_price_cents: seed.unit_price_cents,
      };
    });

    const order: Order = {
      id: input.id,
      customer_ref: input.customer_ref,
      status: input.status,
      created_at: input.created_at,
      lines,
      movements: [],
    };

    for (const line of lines) {
      order.movements.push(
        recordMovement({
          sku: line.sku,
          reason: 'reserve',
          delta_on_hand: 0,
          delta_reserved: line.qty,
          actor: 'demo-operator',
          note: `Order ${order.id}`,
          order_id: order.id,
          created_at: input.created_at,
        }),
      );
    }

    if (input.status === 'fulfilled') {
      const shippedAt = addHours(input.created_at, 1);
      for (const line of lines) {
        order.movements.push(
          recordMovement({
            sku: line.sku,
            reason: 'ship',
            delta_on_hand: -line.qty,
            delta_reserved: -line.qty,
            actor: 'demo-operator',
            note: `Ship ${order.id}`,
            order_id: order.id,
            created_at: shippedAt,
          }),
        );
      }
    }

    if (input.status === 'cancelled') {
      const releasedAt = addHours(input.created_at, 1);
      for (const line of lines) {
        order.movements.push(
          recordMovement({
            sku: line.sku,
            reason: 'release',
            delta_on_hand: 0,
            delta_reserved: -line.qty,
            actor: 'demo-operator',
            note: `Release ${order.id}`,
            order_id: order.id,
            created_at: releasedAt,
          }),
        );
      }
    }

    orders.push(order);
  }

  for (const seed of SEED_PRODUCTS) {
    recordMovement({
      sku: seed.sku,
      reason: 'receive',
      delta_on_hand: seed.opening,
      delta_reserved: 0,
      actor: 'demo-operator',
      note: 'Opening count',
      order_id: null,
      created_at: OPENING_AT,
    });
  }

  seedOrder({
    id: 'ord-1001',
    customer_ref: 'CUST-88',
    status: 'confirmed',
    created_at: '2026-10-25T10:15:00Z',
    lines: [
      { sku: 'SKU-1042', qty: 2 },
      { sku: 'SKU-3301', qty: 4 },
    ],
  });
  seedOrder({
    id: 'ord-1002',
    customer_ref: 'CUST-42',
    status: 'fulfilled',
    created_at: '2026-10-25T14:40:00Z',
    lines: [{ sku: 'SKU-2087', qty: 1 }],
  });
  seedOrder({
    id: 'ord-1003',
    customer_ref: 'CUST-17',
    status: 'cancelled',
    created_at: '2026-10-26T09:05:00Z',
    lines: [{ sku: 'SKU-7714', qty: 5 }],
  });
  seedOrder({
    id: 'ord-1004',
    customer_ref: 'CUST-63',
    status: 'confirmed',
    created_at: '2026-10-27T06:30:00Z',
    lines: [
      { sku: 'SKU-1042', qty: 1 },
      { sku: 'SKU-4410', qty: 5 },
    ],
  });
  seedOrder({
    id: 'ord-1005',
    customer_ref: 'CUST-29',
    status: 'confirmed',
    created_at: '2026-10-27T08:10:00Z',
    lines: [
      { sku: 'SKU-5127', qty: 1 },
      { sku: 'SKU-8820', qty: 1 },
    ],
  });

  async function listStock(): Promise<StockRow[]> {
    await wait();
    return SEED_PRODUCTS.map((seed) => toStockRow(seed.sku));
  }

  async function listMovements(sku: string): Promise<Movement[]> {
    await wait();
    counters(sku);
    return movements.filter((movement) => movement.sku === sku).sort(byNewest).map(clone);
  }

  async function receiveStock(input: ReceiveInput): Promise<StockRow> {
    await wait();
    if (!Number.isInteger(input.qty) || input.qty <= 0) {
      fail(
        'validation_error',
        'Invalid quantity',
        422,
        'Quantity must be a whole number greater than zero.',
      );
    }
    product(input.sku);
    recordMovement({
      sku: input.sku,
      reason: 'receive',
      delta_on_hand: input.qty,
      delta_reserved: 0,
      actor: 'demo-operator',
      note: input.note?.trim() || 'Stock received',
      order_id: null,
      created_at: new Date().toISOString(),
    });
    return toStockRow(input.sku);
  }

  async function adjustStock(input: AdjustInput): Promise<StockRow> {
    await wait();
    product(input.sku);
    if (!Number.isInteger(input.delta) || input.delta === 0) {
      fail(
        'validation_error',
        'Invalid adjustment',
        422,
        'Adjustment must be a whole number other than zero.',
      );
    }
    if (!input.note.trim()) {
      fail(
        'validation_error',
        'Note required',
        422,
        'An adjustment needs a reason note so the count can be explained.',
      );
    }

    const current = counters(input.sku);
    const nextOnHand = current.on_hand + input.delta;
    if (nextOnHand < 0) {
      fail(
        'negative_on_hand',
        'Adjustment would make on-hand negative',
        409,
        `On hand is ${current.on_hand}; an adjustment of ${input.delta} would go below zero.`,
      );
    }
    if (nextOnHand < current.reserved) {
      fail(
        'would_breach_reserved',
        'Adjustment would breach reservations',
        409,
        `${current.reserved} units are reserved; on hand cannot drop to ${nextOnHand}.`,
      );
    }

    recordMovement({
      sku: input.sku,
      reason: 'adjust',
      delta_on_hand: input.delta,
      delta_reserved: 0,
      actor: 'demo-operator',
      note: input.note.trim(),
      order_id: null,
      created_at: new Date().toISOString(),
    });
    return toStockRow(input.sku);
  }

  async function listOrders(status?: OrderStatus): Promise<Order[]> {
    await wait();
    return orders
      .filter((order) => !status || order.status === status)
      .sort(byNewest)
      .map(clone);
  }

  async function createOrder(input: CreateOrderInput): Promise<Order> {
    await wait();

    const customerRef = input.customer_ref.trim();
    if (customerRef.length < 3 || customerRef.length > 40) {
      fail(
        'validation_error',
        'Invalid customer reference',
        422,
        'Customer reference must be between 3 and 40 characters.',
      );
    }
    if (input.lines.length === 0) {
      fail('validation_error', 'Empty order', 422, 'An order needs at least one line.');
    }

    const aggregated = new Map<string, number>();
    for (const line of input.lines) {
      if (!Number.isInteger(line.qty) || line.qty <= 0) {
        fail(
          'validation_error',
          'Invalid quantity',
          422,
          `Quantity for ${line.sku} must be a whole number greater than zero.`,
        );
      }
      product(line.sku);
      aggregated.set(line.sku, (aggregated.get(line.sku) ?? 0) + line.qty);
    }

    const shortLines: ProblemError[] = [];
    for (const [sku, qty] of aggregated) {
      const current = counters(sku);
      const available = current.on_hand - current.reserved;
      if (available < qty) {
        shortLines.push({ sku, requested: qty, available, short_by: qty - available });
      }
    }

    if (shortLines.length > 0) {
      const named = shortLines.map((line) => line.sku).join(', ');
      fail(
        'insufficient_stock',
        'Not enough stock',
        409,
        `${named} ${shortLines.length === 1 ? 'is' : 'are'} short. No stock was reserved.`,
        shortLines,
      );
    }

    const id = `ord-${orderSequence++}`;
    const createdAt = new Date().toISOString();
    const lines: OrderLine[] = [...aggregated.entries()].map(([sku, qty]) => {
      const seed = product(sku);
      return {
        sku: seed.sku,
        name: seed.name,
        qty,
        unit_price_cents: seed.unit_price_cents,
      };
    });

    const order: Order = {
      id,
      customer_ref: customerRef,
      status: 'confirmed',
      created_at: createdAt,
      lines,
      movements: [],
    };

    for (const line of lines) {
      order.movements.push(
        recordMovement({
          sku: line.sku,
          reason: 'reserve',
          delta_on_hand: 0,
          delta_reserved: line.qty,
          actor: 'demo-operator',
          note: `Order ${id}`,
          order_id: id,
          created_at: createdAt,
        }),
      );
    }

    orders.push(order);
    return clone(order);
  }

  async function cancelOrder(id: string): Promise<Order> {
    await wait();
    const order = orders.find((candidate) => candidate.id === id);
    if (!order) {
      fail('not_found', 'Not found', 404, `Order ${id} does not exist.`);
    }
    if (order.status !== 'confirmed') {
      fail(
        'invalid_transition',
        'Invalid transition',
        409,
        `A ${order.status} order cannot be cancelled.`,
      );
    }

    const createdAt = new Date().toISOString();
    for (const line of order.lines) {
      order.movements.push(
        recordMovement({
          sku: line.sku,
          reason: 'release',
          delta_on_hand: 0,
          delta_reserved: -line.qty,
          actor: 'demo-operator',
          note: `Cancel ${order.id}`,
          order_id: order.id,
          created_at: createdAt,
        }),
      );
    }
    order.status = 'cancelled';
    return clone(order);
  }

  async function fulfilOrder(id: string): Promise<Order> {
    await wait();
    const order = orders.find((candidate) => candidate.id === id);
    if (!order) {
      fail('not_found', 'Not found', 404, `Order ${id} does not exist.`);
    }
    if (order.status !== 'confirmed') {
      fail(
        'invalid_transition',
        'Invalid transition',
        409,
        `A ${order.status} order cannot be fulfilled.`,
      );
    }

    const createdAt = new Date().toISOString();
    for (const line of order.lines) {
      order.movements.push(
        recordMovement({
          sku: line.sku,
          reason: 'ship',
          delta_on_hand: -line.qty,
          delta_reserved: -line.qty,
          actor: 'demo-operator',
          note: `Ship ${order.id}`,
          order_id: order.id,
          created_at: createdAt,
        }),
      );
    }
    order.status = 'fulfilled';
    return clone(order);
  }

  return {
    listStock,
    listMovements,
    receiveStock,
    adjustStock,
    listOrders,
    createOrder,
    cancelOrder,
    fulfilOrder,
  };
}

export const api = createMockApi();
