# CircuitMind — supply-chain intelligence

> Your ERP records what you hold. It does not read the news, and it cannot tell
> you that an export licence published this morning leaves one microcontroller
> **5,130 units short by 15 October**. That gap is the whole product.

An AI decision layer that sits **on top of** an existing ERP for electronics
manufacturing. It is not an ERP and never becomes one: no order entry, no
invoicing, no warehouse management. The ERP stays the system of record. We read
from it, resolve what is happening in the outside world against it, and hand a
person a costed plan to approve.

---

## The problem

A procurement team already knows what it holds and what it has ordered. What it
cannot do, at the speed the world moves, is answer the specific question:

> *A trade notice was published this morning. Does it affect **us**, in **our**
> part numbers, and by **how much**, and **when**?*

Market-level advisories ("chip shortage worsens") are not actionable.
Forecasting alone is ordinary — every ERP does some of it. The thing nobody
does is translate an external event into a named part number, a quantity, a
date, and a specific plan.

---

## What it does

Six stages. Each is a separate agent, and each one's output is the next one's
input.

| # | stage | what it does |
|---|---|---|
| 1 | **Event ingestion** | Reads published notices under a constrained JSON schema, so the model can only emit categories, countries and dates that exist in our data. Only events that have **already happened** are analysed — nothing here predicts geopolitics. |
| 2 | **Company-specific exposure** | Resolves each event against our supplier lanes and each part's country of origin. Output is named part numbers and quantities exposed, not an advisory. |
| 3 | **Shortage quantification** | A running stock ledger walks the committed order book and a Holt-Winters forecast against usable inventory, dating every movement. Returns the date cover is lost. |
| 4 | **Substitute verification** | Candidates are retrieved by category, then checked against **each board's** design constraints — rail, footprint, temperature, interfaces — rule by rule. Deterministic; the model has no vote. |
| 5 | **Procurement optimisation** | Suppliers hit by the event are excluded outright. The rest are ranked on quoted price **adjusted for their on-time record**, with lead-time padding applied before feasibility is tested. |
| 6 | **Human approval** | Every plan is shown with the options that were rejected and why. The system issues no orders. Purchase orders are produced only after a named person approves. |

Plus two things that are not in that chain:

- **BOM intake** — a second entry point. Upload a bill of materials for a new
  board (CSV, XLSX, TXT or PDF) and the same machinery answers "can we build
  this, and what do we need to buy?"
- **Ask** — a question-answering assistant over the same tables, with ten
  read-only tools.

---

## The rule the whole system runs on

> **The model chooses which question to ask. The database answers it.**

A language model is used for what it is good at — reading prose, choosing a
tool, explaining a result. It is never the source of a quantity, price, lead
time or date. That is not a claim, it is enforced three ways:

| enforcement | what it does |
|---|---|
| **Constrained decoding** | The category list is injected into the request as a JSON-schema `enum`, so the model physically cannot emit a category that does not join to anything. |
| **A read-only database role** | The assistant connects as `scip_readonly`. `INSERT`, `UPDATE`, `DELETE` and `CREATE` are refused by Postgres itself — verified with the read-only transaction flag deliberately switched off. |
| **An output guard** | Every answer is checked before display. Figures with no tool call behind them are **replaced**; a figure that appears in no tool result is **flagged** in the interface. |

And the compatibility verdict — the decision that puts a part on a board — is a
deterministic rule engine with no model in the path at all.

---

## A worked example, with real numbers

This is the actual output of `python scripts/demo.py`, not an illustration.

```
1  Export licence notice on microcontroller shipments originating in China
2  STM32F407VGT6 matched by supplier lane — 4,000 units in transit exposed
3  Demand 11,130 against 6,000 usable; cover lost 15 October; short 5,130
4  STM32F429VGT6 verified against both boards that carry the original
5  $56,960.50 across three suppliers, everything landing 23 days early
6  Held for approval — no order placed
```

Two details worth reading twice:

**The held shipment does not count.** A purchase order for 4,000 units exists,
but it arrives 9 November — after every order it was meant to cover. A single
subtraction says "you're 1,130 short". The running ledger says **5,130**,
because timing matters. That difference is the point of stage 3.

**The cheapest supplier finishes last.** Mouser quotes $10.85, the lowest price
— and delivered late 7 times out of 13, averaging 9 days over. Their price is
adjusted to $11.62 and 4 days are added to their quote before feasibility is
tested. They end up supplying 130 units of 5,130: only what nobody else had.

Two candidates were also rejected outright, on footprint:

```
[FAIL] STM32F429ZIT6   footprint_id: needs LQFP100_14X14_P050, has LQFP144_20X20_P050
[FAIL] STM32F405RGT6   footprint_id: needs LQFP100_14X14_P050, has LQFP64_10X10_P050
```

Both read almost identically to the original in a description. Neither fits the
board. A similarity score would have ranked them highly; a rule engine does not.

---

## Running it

Requirements: Python 3.9+, Node 20+, PostgreSQL 17, and a
[Groq](https://console.groq.com) API key (free tier is enough).

```bash
# 1. configuration
cp .env.example .env          # then add your GROQ_API_KEY

# 2. database — creates the schema and the seed data
python scripts/init_db.py
python scripts/verify.py      # confirms the numbers hold

# 3. the restricted role the assistant runs as
python scripts/create_readonly_role.py

# 4. the API
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

# 5. the dashboard
cd web && npm install && npm run build && npm start
```

Then open **http://localhost:3000**.

To see the whole chain in the terminal without the UI:

```bash
python scripts/demo.py
```

Rehearsing consumes what is being demonstrated: once a recommendation is
approved the dashboard opens on a green chip with nothing left to sign. To put
it back without rebuilding the chain:

```bash
python scripts/reset_approval.py
```

<details>
<summary>Note on the PostgreSQL instance used during development</summary>

This project ran its own PostgreSQL instance on port **5433**, separate from the
Windows service on 5432, because the superuser password for the existing service
was not recoverable. Rather than reset it, we used the installed binaries to
`initdb` a fresh instance. It turned out to be the better arrangement: the demo
database is disposable and needs no admin rights.

- data directory kept **outside** OneDrive — never let a sync client touch a
  live Postgres data directory
- `trust` auth bound to `127.0.0.1` only. Acceptable for a throwaway instance on
  a non-standard port holding nothing but fabricated data. **Do not copy this
  anywhere real.**
- not a Windows service, so it does not survive a reboot:
  `powershell -ExecutionPolicy Bypass -File scripts\pg_start.ps1`

`docker-compose.yml` is kept as an alternative for machines with Docker.
</details>

---

## Architecture

```
                    news notice                 a new board's BOM
                         │                              │
                         ▼                              ▼
            ┌────────────────────────┐      ┌────────────────────────┐
            │  1 intelligence agent  │      │      BOM intake        │
            │  constrained extract   │      │  parse → resolve →     │
            │  → match → score       │      │  register → buildable? │
            └───────────┬────────────┘      └───────────┬────────────┘
                        └──────────────┬────────────────┘
                                       ▼
                        ┌──────────────────────────┐
                        │  3 supply risk agent     │◀── 2 demand forecast
                        │  running stock ledger    │    (Holt-Winters)
                        └────────────┬─────────────┘
                                     ▼
                        ┌──────────────────────────┐
                        │  4 component agent       │
                        │  retrieve → verify       │  ← deterministic rules
                        └────────────┬─────────────┘
                                     ▼
                        ┌──────────────────────────┐
                        │  5 procurement agent     │
                        │  exclude → adjust → plan │
                        └────────────┬─────────────┘
                                     ▼
                            ╔═══════════════════╗
                            ║  a person signs   ║
                            ╚═════════╤═════════╝
                                      ▼
                            purchase orders, one per supplier
```

Two PostgreSQL schemas keep the product boundary visible in the code itself:

- **`erp`** — the read-only mirror of what an ERP would own: products, BOM,
  components, suppliers, inventory, orders. We never write here.
- **`platform`** — everything our analysis produces: events, impacts, forecasts,
  shortages, alternatives, recommendations, supplier scores.

| layer | technology |
|---|---|
| database | PostgreSQL 17, two schemas, raw SQL via psycopg 3 |
| agents | Python, deterministic rules and arithmetic |
| language model | Groq `openai/gpt-oss-120b`, JSON-schema constrained |
| forecasting | statsmodels, Holt-Winters exponential smoothing |
| API | FastAPI, server-sent events for live runs |
| dashboard | Next.js 16 (App Router, TypeScript), plain CSS |

`ARCHITECTURE.md` has the detail — every agent, every table, every decision.

---

## The dataset

Fabricated, deterministic, and seeded from a fixed RNG so every run is
reproducible.

| | |
|---|---|
| products (boards) | 5 |
| components | 30 |
| BOM lines | 68 |
| suppliers | 10 |
| supplier offers | 88 |
| customer orders | 451 |
| closed purchase orders | 132 (with real receipt dates, which is what makes supplier scoring possible) |
| external events | 7 — all flagged `is_synthetic`, all with `example.invalid` URLs |

**Discrimination is the point, not coverage.** The demo pipeline analyses the one
event that touches a part we hold and leaves the rest in the feed;
`scripts/run_intelligence.py` runs the matcher over all of them. An event only
produces an impact when it resolves to a supplier lane or a country of origin we
actually buy from — a system that reacts to every headline is not intelligent,
and what it declines to act on is as much the evidence as what it does.

---

## Tests

```bash
python -m pytest          # 55 tests
```

Every parser test is a bug that actually happened, found by putting a *realistic*
document through the parser rather than a convenient one — a do-not-populate line
being purchased, a reference designator winning over the real part number, an
item-number column read as a quantity, a title block parsed as a component. They
exist so the next change cannot quietly reintroduce them.

---

## Honest limitations

We would rather state these than be caught by them.

- **No live news ingestion.** Events are seeded fixtures. The extraction path is
  real and runs against a live model; the feed is not.
- **The similarity ranker is word overlap, not semantics.** It ranks a catalogue
  by shared vocabulary. A part described in genuinely different words ranks
  poorly. Vector retrieval is the fix and is mapped out, not built.
- **Images are refused.** OCR would make a model the source of a quantity with
  nothing to check it against — the one place our own rule could not hold. We
  chose the refusal.
- **Raw materials are not modelled.** The lowest level is a part number. A
  gallium or copper event reaches a real buyer indirectly; we cannot trace that
  path yet.
- **`TODAY` is pinned** to 2026-09-03, because the seeded data describes a
  specific week.
- **Sign-in is a demo sign-in.** It names the person so approvals carry a name.
  It is not an access control and the page says so.

---

## Attribution

**CircuitMind** is this team's product. The name comes from
[Shruthi-Joshi/CircuitMind](https://github.com/Shruthi-Joshi/CircuitMind), a
repository by the same team member, and the two share more than a name — parts
of this project came from there and parts are going back.

**Taken from it:** the BOM parser (`services/backend/app/docai/parser.py`),
vendored with attribution in the file and three bug fixes, and the
hash-embedding similarity fallback.

**Going back to it:** `integration/circuitmind/` is a drop-in replacement for
that project's `compatibility_score()`, which accepts package, pin-count and
voltage arguments and discards them — so a candidate can rank highly on a
description while being physically unmountable. Our rule engine plugs into that
seam and rejects it instead, with the reason named. Tested, documented, ready to
hand over.

The two halves are complementary rather than competing: their vector retrieval
finds candidates at catalogue scale, our deterministic rules decide whether one
actually fits the board.
