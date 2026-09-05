# Architecture

> ERP tells you what you have. External intelligence tells you what is changing.
> This connects the two and tells you what to do.

An AI decision layer that sits **on top of** an existing ERP. It is not an ERP and
never becomes one. The ERP stays the system of record; we read from it, combine it
with what is happening outside the company, and recommend an action a human approves.

---

## 1. The one rule

**The model reads. The code decides.**

Every quantity, price, lead time, date and compatibility verdict comes from a
database row or a calculation you could reproduce on paper. The model is only ever
asked to turn unstructured human writing into values our database understands.

A hallucinated number on a purchase order costs real money, so the model is kept
away from every number.

---

## 2. Shape of the system

```
        OUTSIDE THE COMPANY                      INSIDE THE COMPANY
        ───────────────────                      ──────────────────

  a news notice ──▶ [1] Intelligence ─┐
                        (AI)          │
                                      │      ┌── [2] Demand forecast
  a parts list ───▶  BOM intake ──────┤      │       (statistics)
                     (parser)         │      ▼
                                      └─▶ [3] Supply risk ──▶ [4] Component ──▶ [5] Procurement ──▶ HUMAN
                                             (arithmetic)        (rules)          (optimisation)      │
                                                 ▲                                                     ▼
                                                 │                                            PO recommendation
                                     ┌───────────┴────────────┐                               (never an order)
                                     │   erp.*  read-only     │
                                     │   the ERP mirror       │
                                     └────────────────────────┘
```

Two entry points, one engine. Everything after the first step is shared.

---

## 3. The database

Two schemas in one PostgreSQL database, and the split is the product boundary made
visible in code.

| schema | what it is | who writes it |
|---|---|---|
| `erp` | a dummy mirror of what SAP / Oracle / Dynamics would expose | **nobody** — read-only to us |
| `platform` | our analysis: events, impacts, shortages, alternatives, recommendations | us |

In a real deployment the `erp` schema is replaced by a connector and **nothing else
changes**. There is deliberately no order entry, no goods receipt, no invoicing, no
accounting, no warehouse execution.

### `erp` — the mirror

| table | notes |
|---|---|
| `products` | 4 seeded boards, plus any registered from a BOM upload |
| `components` | 30 parts. `specs` is normalised JSONB — the compatibility gate reads it |
| `bom` | `design_constraints` holds what the **board** requires, not what the fitted part offers |
| `suppliers` | 10, with country and city — the geography the news matcher joins on |
| `supplier_components` | 88 offers: price, stock, lead time, MOQ |
| `inventory` | on hand, reserved, safety stock |
| `customer_orders` | 451 rows, 24 months of history plus the committed book |
| `production_plans` | |
| `purchase_orders` | `expected_date` **and** `actual_receipt_date` — the second one is what supplier scoring is built on |
| `purchase_order_items` | |
| `warehouses` | |

### `platform` — ours

| table | written by |
|---|---|
| `external_events` | seeded; `extracted` filled by agent 1 |
| `event_impacts` | agent 1 |
| `demand_forecasts` | agent 2 |
| `shortages` | agent 3, **or** the BOM buildability check |
| `alternatives` | agent 4 |
| `purchase_recommendations` + `_lines` | agent 5 |
| `supplier_scores` | reliability scoring |
| `build_requests` + `_lines` | BOM intake |

`platform.v_stock_position` is the one place net available stock is calculated, so
the arithmetic cannot drift between callers.

---

## 4. The agents

### Agent 1 — Intelligence *(uses AI)*

**Question:** does this event matter to us, and to what exactly?

Two genuinely different jobs, deliberately kept apart:

| | job | tool |
|---|---|---|
| a | understand the article | **the model** |
| b | match it to our suppliers, parts and boards | **SQL** |

The model is shown the article and our controlled category vocabulary
(`SELECT DISTINCT category FROM erp.components`) and **nothing else** — no supplier
list, no stock figures, no quantities. It cannot invent a fact about the business
because it is never given one.

The category list is injected as a JSON-schema `enum`, so under constrained decoding
the model is *physically unable* to emit a category that does not exist in the
database. Tested: with the schema it returns `MCU`; without it, the same model on the
same article invents fields called `origin` and `products` and a category called
`export_control`, none of which join to anything.

**Two matching paths**, recorded in `event_impacts.match_basis`:

| basis | meaning | what is exposed |
|---|---|---|
| `SUPPLIER_LANE` | our supplier sits in the affected place | goods **in transit** |
| `PART_ORIGIN` | the part is **made** there, whoever sells it | **replenishment** |
| `BOTH` | both | both |

The origin path matters: a fab fire in Japan reaches a Murata capacitor bought
through a US distributor, because buying through a distributor does not move the fab.

**Reads:** `external_events`, `suppliers`, `supplier_components`, `components`, `bom`,
`products`, `purchase_orders`, `purchase_order_items`
**Writes:** `external_events.extracted`, `event_impacts`

### Agent 2 — Demand Forecasting *(no AI)*

**Question:** how much will we need?

Holt-Winters exponential smoothing (`statsmodels`) — level, trend, yearly seasonal —
called **as a tool**, fitted on 24 months of shipped orders per product, then exploded
through the BOM into component demand.

**A supporting agent, not the headline.** Every ERP already forecasts demand. It is
here because the shortage calculation needs a number.

Reconciliation uses the standard MRP rule, **forecast consumption**: per month, demand
is the *greater* of the committed order book and the forecast. Adding them would
double-count every order already placed. Monthly figures are prorated into the rolling
60-day window so agent 2 and agent 3 agree exactly.

Only the **uncovered** part (net minus committed) is passed on — the committed orders
are already in agent 3's ledger as real dated movements.

### Agent 3 — Supply Risk *(no AI at all)*

**Question:** do we actually run out, how many, and from when?

Not a subtraction — a **running stock ledger**:

```
open at usable stock
walk forward through the horizon, date by date
subtract each customer order as it falls due
add each purchase order as it lands
the lowest the balance ever reaches is what you are short
```

Timing is the whole point. Demand and supply can balance across a quarter while you
still run dry in week seven, because the parts arrive after the boards were due out.

A flagged PO has its date pushed out by the delay; if that puts it past the horizon it
stops counting as supply. A flagged PO with **no stated delay** is assumed to miss —
we will not invent a duration.

Every ledger row is stored in `shortages.ledger`, so a buyer can check the arithmetic
rather than trust it.

### Agent 4 — Component Intelligence *(no AI)*

**Question:** what else can physically go on this board?

Two stages, kept apart:

- **retrieve** — narrow the catalogue to candidates. Cheap, fuzzy, allowed to be wrong.
- **verify** — decide. Deterministic rules. Never fuzzy, because the output goes on a board.

Judged against `bom.design_constraints` — what the **board** requires, not what the
incumbent part offers. A part used on several boards must satisfy **every** board.

Constraint keys are interpreted by prefix, so a new requirement needs no code change:

| pattern | meaning |
|---|---|
| `min_x` / `max_x` | numeric bound against `spec.x` |
| `rail_voltage_v` | must sit inside `vcc_min_v`–`vcc_max_v` |
| `ambient_temp_min_c` / `_max_c` | the part's range must cover the board's |
| `required_interfaces` | subset check |
| anything else | exact match |

One alias earns its keep: a board's `min_freq_mhz` is checked against the part's
`max_freq_mhz`, because a design floor is compared against a datasheet ceiling.

Candidates that pass but are **only sourceable from affected suppliers** are demoted,
not hidden.

### Agent 5 — Procurement *(no AI)*

**Question:** who do we buy from?

Three questions in order, and the order is the point:

1. **Can we avoid touching the BOM?** Substituting a fitted part means
   re-qualification, so the original wins even at a higher unit price — if it is
   obtainable from unaffected suppliers.
2. **If not, how far does the original get us?** A substitution is then declared
   unavoidable, in those words.
3. **Once swapping anyway, buy the whole quantity the best way.** No partial credit
   for using some of the old part.

Then a stated rule: single-sourcing is usually cheapest, and concentration caused this
shortage — so the split is costed too and taken when the premium is under 5%.

**Supplier reliability** is folded in from 126 closed purchase orders:

- **score** (0–1) — recency-weighted share of deliveries that hit the promised date.
  Adjusts the price ranking: `adjusted = quote × (1 + (1 − score) × 0.15)`
- **lead-time padding** — `(1 − score) × avg days late`, added before asking whether an
  order can arrive in time. A supplier who is habitually late can be ruled out entirely.

Effect: Mouser is cheapest on paper and hits its date 6 times in 13, so it drops from
5,000 units to 130. The plan costs $1,274 more and buys from people who turn up.

### The human gate

`--approve` / the dashboard button sets `status = 'APPROVED'` with a name and timestamp
**in our own database and does nothing else.** There is no code path in this project
that contacts a supplier.

---

## 5. Second entry point — a BOM document

`agents/bom_intake/` — a board arrives as a spreadsheet instead of a news story.

```
file → parse → resolve part numbers → register as a product → buildability → shortages
```

The parser is vendored from **CircuitMind** (Shruthi-Joshi, `docai/parser.py`), which
is genuinely standalone. Three bugs were fixed on the way in; the worst was an MPN
regex that required a hyphen, making every part like `STM32F407VGT6` invisible in free
text, PDF and OCR.

Handles **CSV, TSV, XLSX, PDF, plain text**. Images need OCR (Tesseract), not wired up.

**Matching is deliberately narrow** — `EXACT`, `NORMALISED` (case, whitespace,
distributor suffixes like `-ND` and `-TR`), or `UNKNOWN`. **No fuzzy matching**:
`STM32F407VGT6` and `STM32F407VET6` differ by one character and by half the flash. An
unmatched line costs a minute; a wrongly matched one ships.

**Registration is permanent.** The board becomes a row in `erp.products` with real
`erp.bom` lines, so the news monitor, the forecaster and the shortage calculation all
watch it from that moment — with no code change.

**The build check is incremental, not isolated.** "Do we have 500 chips?" is the
flattering question and the wrong one — that stock is already promised to other
customers. The real question is whether we can build this *on top of* the committed
order book.

**Derived design constraints are deliberately weak.** A BOM document carries part
numbers, not footprints and rail voltages — those live in CAD and PLM. Intake derives
only `footprint_id` and `pinout_family`, read straight off the fitted part, and does
not guess a voltage or a temperature grade.

---

## 6. Where the AI is

| step | AI? | what would go wrong otherwise |
|---|---|---|
| Reading a news article | **yes** | no rule covers every way a journalist writes "chip" |
| Identifying an unrecognised part | **yes** | text overlap alone matched an op-amp to three CAN chips |
| Reading a spreadsheet | no | columns have headings; it is parsing |
| Forecasting demand | no | a hallucinated forecast becomes a hallucinated order |
| Calculating the shortage | no | it must come out identical every run |
| Checking a part fits | no | "looks similar" is not "will physically mount" |
| Choosing a supplier | no | prices on a signed PO must match the supplier's |
| Answering a question | **yes** | only to pick the query; the database returns the number |
| Approving anything | no | there is no code path from a model to an approval |

### The three enforcements

The table above is a design intention. These make it structural.

**Constrained decoding.** The category list is injected into the request as a
JSON-schema `enum`, so the model cannot emit a category that joins to nothing.
Tested: with the schema the model returns MCU / China / 2026-09-20; without it,
the same model on the same article invents a field called `origin` and a
category called `export_control`.

**A read-only database role.** The assistant connects as `scip_readonly`, created
by `scripts/create_readonly_role.py`. Two independent locks:

    privileges     SELECT granted; INSERT, UPDATE, DELETE, TRUNCATE never are
    read-only txn  default_transaction_read_only forced on for the role

The second can be switched off by the role itself, so it is not the guarantee —
it is the belt. Verified by turning it off and retrying: every write still
refused with `permission denied`.

**An output guard** (`agents/assistant/guard.py`). Every answer is checked before
display:

    BLOCK   figures present, no tool called      -> the answer is replaced
    FLAG    a figure in no tool result           -> annotated in the interface

Different strengths on purpose. The first has no legitimate case. The second is
usually the model doing arithmetic, and suppressing a real answer over that would
be worse than showing a caution beside it. Digits inside part codes are ignored —
`STM32F407VGT6` is a name, not a claim.

**Model:** `openai/gpt-oss-120b` on Groq, with JSON-schema constrained decoding.
Free tier: 1,000 requests/day, **8,000 tokens/minute** — one event costs ~1,000 tokens,
so a seven-event run sits on the per-minute ceiling and retries with backoff.

Three interchangeable readers behind one interface: `GroqExtractor` (hosted),
`OllamaExtractor` (local, unusable on 8 GB of RAM), `FixtureExtractor` (hand-written,
tagged `extractor='fixture'` so it can never pass as model output).

---

## 7. The API

FastAPI over the agents. `api/main.py` is assembly only — 67 lines of CORS,
pool lifecycle and router registration. It was 805 lines holding every endpoint,
the SSE plumbing, the pipeline orchestration and a serialisation fix; nothing was
wrong with any one of them, the problem was that they were together.

    api/config.py          values the whole API agrees on (TODAY)
    api/serialization.py   database rows to JSON (NUMERIC arrives as Decimal,
                           which the JSON encoder renders as a *string* — every
                           .toFixed() in the browser threw until this was fixed
                           in one place)
    api/streaming.py       server-sent events; agents are synchronous, so work
                           runs on a thread and frames arrive through a queue
    api/pipeline.py        the tail both pipelines share once a shortage exists
    api/routers/           health, catalogue, recommendations, assistant, runs, bom

The split was a move, not a rewrite: route bodies were lifted verbatim rather
than retyped. A captured baseline of every endpoint's response shape proved the
surface unchanged — and caught four regressions on the way, all missing imports
that a clean module import cannot reveal because route bodies do not execute on
import.

```
GET   /api/health
GET   /api/overview                        the position right now
GET   /api/events                          the news feed
GET   /api/impacts                         what each event touched
GET   /api/shortages
GET   /api/suppliers                       delivery scorecards
GET   /api/recommendations                 recommendations + approvals
POST  /api/recommendations/{id}/approve
POST  /api/bom/preview                     parse a file without committing
POST  /api/run/news                        disruption pipeline   (SSE)
POST  /api/run/bom                         new-board pipeline    (SSE)
```

**Streaming.** Both pipelines emit Server-Sent Events, one per step, so the UI shows
each agent finishing rather than freezing and dumping an answer. They are POSTs with
bodies, so the browser's `EventSource` cannot be used — the frontend reads the frames
off `fetch`'s `ReadableStream`.

**One connection per request.** psycopg connections are not thread-safe and FastAPI
runs sync endpoints in a threadpool; a shared module-level connection would work in
testing and corrupt itself under two simultaneous clicks.

### Known weakness

**The pipeline endpoints run all five agents; the agents are not individually
callable.** The API is currently *less* capable than the command line, where each
agent runs standalone. The agents already hand off through the database, so this is a
packaging problem, not a design one. It should be:

```
POST /api/agents/intelligence    {external_id}
POST /api/agents/demand          {horizon_days}
POST /api/agents/supply-risk     {event_id?}
POST /api/agents/component       {component_id}
POST /api/agents/procurement     {component_id}
POST /api/agents/reliability     {}
```

with `/api/run/news` kept as a convenience wrapper that calls them in order.

---

## 8. The frontend

`web/` — Next.js 16 (App Router, TypeScript), plain CSS with an oklch token
system. No component library.

Organised around one principle: **the answer first, the evidence underneath.**

1. **The verdict** — a sentence, in plain words. *"You run out on 15 October."*
2. **The action** — one recommendation, one button.
3. **The evidence** — five collapsed sections. Someone who trusts the verdict never
   opens one; someone who does not can reach every check and the full ledger.

Part numbers are given plain-English names (`STM32F407VGT6` → "the controller chip in
your motor boards"), dates render as "15 October", and every step carries an
`AI` / `no AI` tag so the architecture argument is visible without explanation.

### Screens

| route | what it is for |
|---|---|
| `/login` | the pitch and a demo sign-in. Names the person so approvals carry a name; explicitly not an access control, and the page says so |
| `/` | the position right now — what is at risk, what needs a decision |
| `/events` | the feed, including the six of seven events correctly ignored |
| `/shortages` `/suppliers` | the underlying tables |
| `/recommendations` | each row reads as a sentence: what to do, what changes, why it exists, whether it works |
| `/recommendations/[id]` | the verdict, then five collapsed evidence sections, then approval and the purchase orders |
| `/bom` | upload, editable quantities, unknown-part resolution, the constraint gate |
| `/ask` | the assistant, with every answer's queries one click away |

### Two decisions worth defending

**"How I got this."** Every assistant answer carries the tool calls that produced
it, rendered as tables rather than JSON — the person deciding whether to spend
$56,960 usually does not read JSON. The raw result stays one click away for
someone who does.

**The constraint gate.** Before a substitute search runs, an engineer can set up
to five non-negotiables — supply rail, footprint, pin count, manufacturer,
country of origin. Five is a deliberate cap: a gate with twelve conditions is
not a gate, it is a search that returns nothing. They are enforced by the same
rule engine as a board's own constraints, so a candidate that fails one is
rejected with the reason named.

---

## 9. Running it

```bash
# 1. database (after a reboot)
powershell -ExecutionPolicy Bypass -File scripts\pg_start.ps1

# 2. api
python -m uvicorn api.main:app --port 8000

# 3. dashboard
cd web && npm run dev        # http://localhost:3000
```

Command line, no browser needed:

```bash
python scripts/demo.py --scenario both --pause --approve "Your Name"
python scripts/demo.py --offline          # no network at all
```

---

## 10. Stack

| layer | choice | why |
|---|---|---|
| Database | PostgreSQL 17 | JSONB for specs, schemas for the ERP boundary |
| Agents | Python 3.9, raw SQL via psycopg 3 | the arithmetic must be inspectable |
| Forecasting | statsmodels (Holt-Winters) | 24 monthly points; ARIMA needs more, GBMs would overfit |
| Model | `openai/gpt-oss-120b` on Groq | free, fast, supports JSON-schema constrained decoding |
| Similarity | hash embeddings, in memory | 30 parts is a list comprehension; pgvector at this scale is theatre |
| API | FastAPI + SSE | agents are Python; streaming makes the pipeline legible |
| Frontend | Next.js 15, plain CSS | no build-time surprises, full control of the look |

---

## 11. The assistant

`agents/assistant/` — a question in English, answered from the same tables the
dashboard reads.

This is **not** retrieval-augmented generation, though it is often called that.
Nothing is embedded and no text is stuffed into a prompt hoping the model reads
it correctly. The model's only job is to choose which question to ask; the answer
comes back as data.

Ten read-only tools:

    find_component            stock_position           demand_forecast
    stock_ledger              events_affecting_inventory
    list_suppliers            supplier_reliability
    inventory_overview        current_shortages        pending_recommendations

Each is a SELECT. Tools take a part as free text and resolve it internally, so
the model does not chain two calls; ambiguity comes back as a list of candidates
for the user to choose between. Nothing writes, and `approve` is deliberately
**not** exposed: a model that can approve its own plan is exactly what the
project's one rule forbids.

---

## 12. Purchase orders

Produced only after a named person approves — `agents/procurement/po.py` refuses
anything else, and the API returns `409` for a pending recommendation. There is
no URL that yields a purchase order for an unapproved plan.

**One PDF per supplier**, because that is what a purchase order is. A plan
spanning three suppliers is three orders with three numbers and three delivery
dates. The combined copy exists for internal review and is labelled as such: page
two carries a second supplier's quantities and unit prices, so sending it to the
first would show them what a competitor quoted.

Numbering is derived — `PO-<recommendation>-<supplier code>` — so regenerating
produces the same numbers rather than consuming a counter. Every page states
that nothing has been transmitted and that issuing the order is a human act.

---

## 13. Tests

`python -m pytest` — 55 tests, no network, no model.

    tests/test_rules.py             the compatibility gate, rule by rule
    tests/test_parser.py            every BOM bug that actually happened
    tests/test_guard_and_intake.py  the guard, quantities, overrides, the PO gate

A test whose result depends on a language model is not a regression test, it is a
weather report — so none of them call one. Database-backed tests skip rather than
fail when Postgres is absent.

---

## 14. Honest limitations

- **News does not arrive by itself.** Events are seeded rows. A live feed is a
  connector — polling, deduplication, full-text fetch, a cheap relevance pre-filter
  before spending a model call. Roughly half a day, and the least interesting half.
- **A board registered from a spreadsheet gets weak compatibility checks** — footprint
  and pinout only, because a parts list carries nothing else. Two checks where an
  established board gets eleven.
- **The forecast looks better than it is.** The order history is generated with a small
  noise term, so in-sample RMSE of 11–50 units is implausible. Real demand is far messier.
- **24 months is exactly the minimum** for a yearly seasonal term. It fits; it is thinly
  evidenced, and every forecast prints that caveat.
- **One unrecognised part blocks a build** — deliberately. The system will not call a
  build feasible while a part on it is unknown.
- **Agents are not individually addressable over HTTP** (see §7).
- **OCR is not wired up.** Images and scanned PDFs are the one format not covered.
- **All data is fabricated.** Real distributor names appear as realistic labels; every
  price, stock figure and lead time is invented. The suppliers the disruption story
  touches are fictional companies on purpose — no invented trade-restriction narrative
  is attached to a real named company. Every seeded event carries `is_synthetic = TRUE`.
