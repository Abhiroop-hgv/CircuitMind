# CircuitMind — master context prompt

Paste this whole file into a model before asking it to work on CircuitMind. It is
written to be read once and held in memory. Everything below is verified against
the running code and database, not recalled from a deck.

---

## 1. What CircuitMind is, in one paragraph

CircuitMind is an **AI decision layer that sits on top of an ERP** for
semiconductor and PCBA manufacturers. An ERP records what you hold; it cannot
read a trade notice and tell you which of your part numbers that notice hits, by
how much, and by when. CircuitMind closes that gap. It reads events that have
**already been published** — export controls, port closures, fab incidents —
resolves them against your bill of materials, supplier lanes and open purchase
orders, and produces a costed procurement plan for a person to approve. It is
**not an ERP**: no order entry, no invoicing, no warehouse, no accounting. It
reads from the system of record and writes nothing back to it.

---

## 2. The invariants — never violate these

These are the product's spine. A change that breaks one of them is wrong even if
it passes tests.

1. **The model is never the source of a number.** Quantities, supplier stock,
   component specifications, compatibility, prices and lead times all come back
   from PostgreSQL. The language model reads prose and chooses *which query to
   run*. It does not supply the figure.
2. **Only analyse what already happened.** The system never predicts geopolitics
   or forecasts an event. Demand forecasting (Holt-Winters over historical
   consumption) is allowed and is a different thing.
3. **Nothing is ordered automatically.** The system drafts a purchase order per
   supplier and stops. A named person approves before anything is generated.
   There is no code path that transmits an order.
4. **Compatibility is decided by rules, not resemblance.** A deterministic rule
   engine (`agents/component/rules.py`) decides whether a substitute part is
   acceptable. Similarity ranking may *propose* candidates; it may never approve
   one. Two parts can read almost identically and differ by a package that will
   not sit on the footprint.
5. **Unknown parts are never auto-matched.** If a BOM line cannot be resolved to
   a catalogue part, candidates are ranked and shown to a person to choose.
6. **The assistant is read-only at the database level.** It connects as a
   restricted Postgres role; the database itself refuses writes. This is a
   second, independent lock on top of the tool definitions.

---

## 3. Domain vocabulary

- **BOM (bill of materials)** — the parts list for one board, one line per part.
- **MPN (manufacturer part number)** — e.g. `STM32F407VGT6`. The identity of a part.
- **Reference designator** — the position on the board (`R1`, `C12`, `Q1-Q6`).
  Frequently mistaken for a part number by naive parsers.
- **DNP (do not populate)** — a BOM line with quantity 0. The footprint exists
  but nothing is fitted. Must survive parsing as 0, never coerced to 1.
- **Footprint / land pattern** — the copper shape a part solders onto, e.g.
  `LQFP100`. A part with `LQFP144` will not fit an `LQFP100` pad, however similar
  the datasheet reads. This is the classic false-positive substitution.
- **Lead time** — days between placing an order and receiving it.
- **On-time record** — the share of a supplier's past deliveries that arrived by
  the promised date. Used to pad lead times and to weight the split.
- **Coverage** — how much of a required quantity you can actually obtain.
- **Shortage** — required minus obtainable, with a date attached.

---

## 4. Data model

PostgreSQL, **two schemas**, deliberately separated so the product boundary is
visible in the code:

**`erp`** — a read-only mirror of the system of record. We never write here.
```
products  bom  components  suppliers  supplier_components  inventory
warehouses  customer_orders  purchase_orders  purchase_order_items
production_plans
```

**`platform`** — everything our analysis produces.
```
external_events  event_impacts  demand_forecasts  shortages  alternatives
supplier_scores  purchase_recommendations  purchase_recommendation_lines
build_requests  build_request_lines  v_stock_position (view)
```

Key columns to know:
- `platform.purchase_recommendations`: `id, event_id, original_component_id,
  qty_required, need_by, strategy, rationale, requires_bom_change, total_cost,
  latest_arrival, considered, status, approved_by, approved_at, created_at`
- `platform.purchase_recommendation_lines`: `recommendation_id, supplier_id,
  component_id, quantity, unit_price, line_total, lead_time_days,
  expected_arrival, supplier_reliability`
- Status values: `PENDING_APPROVAL` → `APPROVED`.
- `external_events.extracted` is JSONB. **Event type lives at
  `extracted->>'event_type'`, not in a column.** A common mistake.

**`TODAY` is pinned to 2026-09-03** in `api/config.py`, because the seeded data
describes one specific week. `WATCH_MPN = "STM32F407VGT6"`.

---

## 5. The five agents, plus the assistant

Each lives in `agents/<name>/` with an `agent.py` entry point.

1. **`intelligence`** — reads a published notice. Extracts structured fields with
   Groq under a **JSON schema with the category list as an `enum`**, so the model
   cannot emit a category the database does not have. Matches the event to
   components and scores severity. Files: `extract.py`, `groq_extract.py`,
   `local_extract.py`, `match.py`, `score.py`, `schema.py`.
2. **`demand`** — Holt-Winters forecasting via statsmodels (`forecast.py`).
   **Per month it takes the larger of committed orders vs forecast, never the
   sum** — adding them counts the same customer twice.
3. **`supply_risk`** — runs a month-by-month running stock ledger. **A delivery
   landing after the date it was needed is excluded, not netted off**; it is
   marked `OUTSIDE_HORIZON`.
4. **`component`** — retrieves substitute candidates and verifies each against
   the board's constraints, rule by rule. `assess(component_id,
   affected_supplier_ids, extra_constraints=None)`. Manufacturer and
   country-of-origin are merged into the spec before evaluation.
5. **`procurement`** — excludes suppliers the event touches, pads lead times by
   each supplier's on-time record, and ranks the rest on price adjusted for
   reliability. Constants: `RISK_PREMIUM = 0.15`,
   `DUAL_SOURCE_PREMIUM_LIMIT = 0.05`, `MAX_LINES = 3` (buyers do not want six
   POs for one part). `po.py` renders the PDFs.

**`assistant`** — a **tool-calling agent, not RAG**. The model picks a tool; the
database answers. Ten read-only tools in `agents/assistant/tools.py`:
```
current_shortages      demand_forecast        events_affecting_inventory
find_component         inventory_overview     list_suppliers
pending_recommendations  stock_ledger         stock_position
supplier_reliability
```
`guard.py` post-checks every answer: **BLOCK** if it contains figures with no
tool call behind it, **FLAG** if a figure appears that is in no tool result.
Optional tool params must be typed `["string","null"]` or Groq rejects the call.

**`bom_intake`** — parses PDF (pdfplumber tables first, text heuristics as
fallback), XLSX, CSV, TXT. Detects header order by scoring. Refuses scanned
PDFs with no text layer rather than silently returning zero rows. **Images are
refused by design** — OCR would make a model the source of a quantity with
nothing to check it against.

---

## 6. The rule engine

`agents/component/rules.py`. Constraint keys:
```
min_<field>          spec[field] >= value
max_<field>          spec[field] <= value
rail_voltage_v       spec.vcc_min_v <= value <= spec.vcc_max_v
ambient_temp_min_c   spec.temp_min_c <= value
ambient_temp_max_c   spec.temp_max_c >= value
required_interfaces  every listed interface present in spec.interfaces
<field>              exact match
```
Note the alias in `_lookup()`: a design needing `min_freq_mhz: 160` is compared
against the part's `max_freq_mhz` — its rated ceiling — because that is the
number a datasheet publishes. Design floor vs datasheet ceiling.

---

## 7. Stack and layout

- **Backend**: FastAPI (Python). **There is no Node backend** — a claim to the
  contrary appears in an old deck and is wrong.
- **DB access**: psycopg 3 with `psycopg_pool.ConnectionPool`. Helpers in
  `db/connection.py`: `connect()`, `pooled()`, `connect_readonly()`.
- **Model**: Groq, `openai/gpt-oss-120b`, with constrained JSON decoding.
- **Frontend**: Next.js 16 App Router, TypeScript, oklch design tokens.
- **Deployment**: Render for both halves. There is no Vercel config.
- **Tests**: 55, all passing. `pytest tests/`.

```
agents/{intelligence,demand,supply_risk,component,procurement,assistant,bom_intake}/
api/{main,config,serialization,streaming,pipeline}.py
api/routers/{health,catalogue,recommendations,assistant,runs,bom}.py
db/connection.py
integration/circuitmind/     drop-in compatibility_score for a teammate's repo
scripts/                     demo, seeding, reset, sample BOM generators
tests/                       conftest, test_rules, test_parser, test_guard_and_intake
web/src/app/                 / /ask /bom /events /login /recommendations
                             /recommendations/[id] /runs /shortages /suppliers
artifacts/                   submission decks + architecture diagram
```

`api/main.py` is 67 lines of assembly only. Route bodies were **moved verbatim**
during the refactor, not retyped — retyping is where a refactor changes behaviour
by accident.

---

## 8. HTTP surface

```
GET  /api/health
GET  /api/overview          GET  /api/events          GET  /api/impacts
GET  /api/shortages         GET  /api/suppliers
GET  /api/recommendations   GET  /api/recommendations/{id}
GET  /api/recommendations/{id}/po           (single or ?supplier_code=)
GET  /api/recommendations/{id}/po.zip       GET .../po/manifest
POST /api/recommendations/{id}/approve
POST /api/ask               POST /api/bom/preview
POST /api/run/news          POST /api/run/bom          (SSE-streamed)
```
The frontend de-duplicates requests with an 8s TTL cache in `web/src/lib/api.ts`.

---

## 9. The canonical worked example

These are live figures from the database — use them, do not invent others.

> An export licence requirement is announced for microcontroller and logic IC
> shipments from China. It hits **STM32F407VGT6**, used on the MC-3000 and SD-220
> boards. Coverage leaves **5,130 units short, needed by 15 October**. The rule
> engine clears **STM32F429VGT6** as a substitute and rejects two look-alikes on
> footprint — LQFP144 and LQFP64 against an LQFP100 land pattern. Procurement
> splits the buy three ways, weighted by on-time record:
>
> | Supplier | Units | Unit | Line total | Arrives | On-time |
> |---|---|---|---|---|---|
> | Avnet Asia Pte Ltd | 3,000 | $11.05 | $33,150.00 | 15 Sep | 95% |
> | DigiKey Electronics | 2,000 | $11.20 | $22,400.00 | 10 Sep | 99% |
> | Mouser Electronics | 130 | $10.85 | $1,410.50 | 22 Sep | 98% |
>
> **5,130 units, $56,960.50, all landed by 22 September — 23 days early.** It sits
> at `PENDING_APPROVAL` until a person signs.

---

## 10. Known limitations — state them, do not paper over them

- **No live news ingestion.** Events are seeded fixtures. The extraction path is
  real and runs against a live model; the feed is not.
- **The similarity ranker is word overlap, not semantics.** A part described in
  genuinely different words ranks poorly. Vector retrieval is the fix, mapped out
  and not built.
- **Images are refused.** A deliberate choice, per invariant 1.
- **Raw materials are not modelled.** The lowest level is a part number; a
  gallium or copper event cannot be traced to a buyer yet.
- **`TODAY` is pinned** to 2026-09-03.
- **Sign-in is a demo sign-in.** It names the person so approvals carry a name.
  It is not access control, and the page says so.
- **Buyer identity in `po.py` is placeholder** — `Kestrel Electronics Pvt Ltd`,
  GST `33AABCK1234M1Z5`.

---

## 11. Conventions when working on this code

- Match the surrounding style: comments explain *why*, not *what*.
- Prefer a database answer over a computed guess; prefer a refusal over a
  fabricated figure.
- When a filter matches nothing, distinguish **"the filter matched nothing"**
  from **"nothing is at risk."** Conflating them once produced a dangerously
  false answer.
- Never f-string a value into SQL. Use parameters, or `psycopg.sql.Literal` where
  a parameter is not allowed (e.g. `CREATE ROLE ... PASSWORD`).
- `connect()` opens a transaction; use `psycopg.connect(url, autocommit=True)`
  for DDL.
- Import-checking a module does not execute route bodies. Use pyflakes to catch
  undefined names after a refactor.
- Run `pytest tests/` before claiming anything works.
