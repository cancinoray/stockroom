# Front-end Design System

The visual and interaction contract for Stockroom's UI. This documents what is implemented in
`frontend/`; it is not a separate mockup. The running prototype at `http://127.0.0.1:5173/` is the
reference implementation.

## 1. Direction

**Subject:** a working stockroom — shelf labels, bin tickets, pick sheets, hi-vis safety marks,
concrete floors.

**Audience:** order-desk staff and warehouse operators who use this all day. The interface is a
tool, not a marketing page; it should feel like equipment that belongs in the building.

**Job:** make stock, reservations and order state readable in one glance, and make every write
explainable. The visual language follows from that: labels, ledgers, counts and physical tags.

**Deliberately rejected:** the three common AI-dashboard defaults — cream + serif + terracotta,
near-black + acid accent, and the dense hairline broadsheet. Also rejected: rounded cards with
soft shadows, gradients, decorative icons, and generic SaaS blue.

## 2. Tokens

All tokens live in `frontend/src/index.css` under Tailwind v4 `@theme`.

### Colour

| Token | Hex | Use |
| --- | --- | --- |
| `--color-ink` | `#17232b` | Primary text, header, available stock |
| `--color-paper` | `#eeeae1` | App background |
| `--color-card` | `#f8f5ed` | Panels, bin tickets, inputs on paper |
| `--color-line` | `#d5d0c4` | Borders, rules, empty gauge track |
| `--color-steel` | `#66737c` | Secondary text, metadata, labels |
| `--color-signal` | `#f05a28` | Primary action, reserved stock, active nav |
| `--color-ok` | `#2f6b52` | Confirmed orders, healthy availability |
| `--color-alert` | `#a63a2b` | Short stock, invalid transitions, low-stock marks |

Rules:

- Colour never carries meaning alone. Low stock also has the word `LOW`; errors also have text.
- No gradients except the reserved hatch. No branded shadows.
- One accent (`signal`) for action; one warning (`alert`) for failure. Do not use either decoratively.

### Spacing and shape

- 4px base spacing; ordinary gaps are `0.5rem`–`1.5rem` (`gap-2`–`gap-6`).
- Square corners everywhere. Borders are `1px`; the active bay is `3px` `signal`.
- Panels use borders, not shadows. Only dialogs and drawers get `shadow-2xl`.
- Content width is capped at `1280px`; page padding is `1rem` on mobile, `1.5rem` from `sm`.

## 3. Typography

| Role | Face | Weights | Usage |
| --- | --- | --- | --- |
| Display | Barlow Condensed | 600, 700 | Wordmark, screen titles, section headings, large counts |
| Body | IBM Plex Sans | 400, 500, 600 | Descriptions, controls, names, prose |
| Data | IBM Plex Mono | 400, 500 | SKUs, quantities, money, timestamps, reasons, labels |

Rules:

- Display type is uppercase with tight tracking; use it for structure, not paragraphs.
- All numbers that can be compared are mono and align by their digits.
- Labels are `10–11px`, mono, uppercase, `0.12em` tracking, steel. They are structural, not decoration.
- No type below `10px`; body copy does not go below `0.875rem`.

## 4. Layout

```
┌ STOCKROOM / MAIN ───────────────────────── operator · shift ┐
│  A INVENTORY  │  B PLACE ORDER  │  C ORDERS               │
├─────────────────────────────────────────────────────────────┤
│  eyebrow / screen title / one-line purpose       stats      │
│  ┌ chart or summary panel ───────────────────────────────┐  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌ bin ticket ───────────────────────────────────────────┐  │
│  └───────────────────────────────────────────────────────┘  │
│  footer: product · warehouse · prototype note               │
└─────────────────────────────────────────────────────────────┘
```

- The header is a warehouse sign. The wordmark is the largest type on the page; `MAIN` is a stamped
  location, not a button.
- Navigation is labelled as physical bays (`A`, `B`, `C`). The letters are locations in a warehouse,
  not decorative numbering.
- Each screen opens with an eyebrow, a display title, and one sentence stating the job.
- The Inventory screen puts a stock chart above the bin-ticket list. The chart is an overview; the
  tickets are the record. Both read from the same query.
- Side-by-side at `lg` where the task benefits: stock picker + order ticket, order list + order
  detail.

## 5. Components

### Bin ticket (`StockTicket`)

The signature component. A stock row is a physical bin ticket:

- Perforated left edge: a 9px strip of paper-coloured dots over the card.
- Sku in mono, item name in body, price in `10px` mono.
- On hand / reserved / available as three labelled metrics; available turns alert-red at zero.
- Reorder point with a two-tone gauge: ink for on-hand, `signal` hatch for reserved. Low rows get a
  diagonal hazard strip and a rotated `LOW` stamp.
- Actions are always visible: History, Receive, Adjust. No hover-only affordances.

### Stock chart (`StockChart`)

- Horizontal bars, one per SKU, sorted **lowest available first**.
- Bar length is on-hand on a shared scale (`max(on_hand)`); the reserved share is hatched inside it.
- Low rows are outlined in alert red; the SKU line also says `LOW`.
- Legend: solid ink = available, hatch = reserved, bar = on hand. The scale is printed below.
- CSS bars only; no chart library. The same data is repeated as text for each row, so the visual is
  supplementary rather than the only access path.

### Navigation (`BayNav`)

- Three bay tabs, letter + label. Active tab: card background, ink text, 3px `signal` bottom rule.
- Horizontal scroll on narrow screens; no hamburger, because there are only three destinations.

### Dialog and drawer

- Centred dialog for receive/adjust; right-side drawer for movement history.
- Both use `role="dialog"`, `aria-modal="true"`, a labelled heading, `Escape` to close, body scroll
  lock, and focus moved into the panel on open.
- Destructive actions are outlined alert-red; the primary action is solid `signal`.

### Movement ledger

- A receipt: date, reason, note, actor, order reference, on-hand delta, reserved delta, balance.
- Dashed row rules. Deltas are signed and right-aligned; zero shows an em dash.
- On mobile the row reflows to date, reason, then a three-column delta strip with inline labels.

### Status and feedback

- `StatusPill`: confirmed = `ok`, fulfilled = ink, cancelled = steel. Uppercase mono, square border.
- `ProblemNotice` uses `role="alert"`, the problem title, the human-readable detail and the trace id.
- Success (order confirmed) uses the green notice variant; it never replaces the updated record.
- Empty states say what is missing and what to do next.

## 6. States

| State | Treatment |
| --- | --- |
| Loading | One mono line (`Reading the shelf…`); no spinners, no skeleton shimmer |
| Empty | Dashed panel with a title, a sentence and an action if one exists |
| Error | Red-ruled notice with title, detail and trace id; the form stays open |
| Pending mutation | Submit label changes (`Reserving…`, `Receiving…`), control disabled |
| Low stock | Hazard edge + `LOW` stamp + alert-red available count + outlined chart bar |
| Invalid input | Alert-red inline message, `aria-invalid`, submit disabled |
| Disabled | 45% opacity and `cursor: not-allowed`; disabled controls remain legible |

## 7. Voice and content

- Plain, active, sentence case: “Reserve stock”, “Receive stock”, “Cancel order”.
- Name things by what the operator controls, not how the system is built.
- Errors state what happened and what to do next; they do not apologise.
- No emoji, no exclamation marks, no “Oops”, no filler in labels or empty states.
- Currency is PHP, displayed from integer centavos. Dates render in the viewer's timezone.

## 8. Responsive

- Breakpoints follow Tailwind defaults: `sm` 640, `md` 768, `lg` 1024.
- `md`: the stock chart becomes two columns, bin tickets move from stacked to a six-column grid.
- `lg`: Place order and Orders split into list + detail.
- 390px is the tested mobile floor: nav scrolls, chart is one column, tickets stack, ledger reflows.
- No horizontal overflow is acceptable at 390px.

## 9. Accessibility

- Visible `:focus-visible` outline: 2px `signal`, 2px offset. Do not remove it.
- Every input has a label; icon-only controls would need an `aria-label` (there are none today).
- Low stock and errors are not colour-only.
- Filters use `aria-pressed`; the selected order uses `aria-current`; the active bay uses
  `aria-current="page"`.
- Dialogs and drawers move focus in, trap `Tab`, close on `Escape`, restore focus to the trigger,
  and restore page scrolling on close.
- Invalid quantities and required notes are blocked before submit, with an inline message and
  `aria-invalid` on the field; the mock's `422` remains defence in depth.
- Gauges expose an `aria-label` with the numbers; chart rows repeat the numbers as text.
- Motion is suppressed under `prefers-reduced-motion`.

## 10. Motion

One orchestrated page-load moment, not scattered effects:

- Header rule draws in over 480ms.
- Inventory tickets stagger in at 30ms intervals, 360ms each.
- Hover changes border/background only; no lifts, bounces or scale.
- All animation collapses to ~0ms under reduced motion.

## 11. Implementation map

| Concern | File |
| --- | --- |
| Tokens, base styles, component classes, motion | `frontend/src/index.css` |
| Shell and screen switch | `frontend/src/App.tsx` |
| Header and bay navigation | `frontend/src/components/Header.tsx`, `BayNav.tsx` |
| Stock chart and ticket | `frontend/src/components/StockChart.tsx`, `StockTicket.tsx`, `StockGauge.tsx` |
| Dialog and ledger | `frontend/src/components/Dialog.tsx`, `MovementDrawer.tsx`, `MovementList.tsx` |
| Modal focus trap, Escape and focus restore | `frontend/src/lib/useModalFocus.ts` |
| Status and errors | `frontend/src/components/StatusPill.tsx`, `ProblemNotice.tsx` |
| Screens | `frontend/src/screens/InventoryScreen.tsx`, `PlaceOrderScreen.tsx`, `OrdersScreen.tsx` |
| Formatting | `frontend/src/lib/format.ts` |

The mock service seam is `frontend/src/api/`; screens never call `fetch` directly. P3 swaps the mock
for the generated client without changing this visual layer.

## 12. Change rules

1. New colour or type role: add a token here and in `index.css`; do not hard-code a hex in a component.
2. New component: define its states (default, pending, disabled, error, empty) before styling it.
3. Do not introduce a component library or chart library without an ADR; the current system is small
   enough to own.
4. Do not add rounded corners, gradients, decorative icons, or a second accent.
5. Any new screen repeats the shell: eyebrow, display title, one-sentence job, then the work.
6. Test at 1440px and 390px, with keyboard focus visible and reduced motion enabled.
