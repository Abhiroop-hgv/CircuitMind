# CircuitMind — Technical Architecture

**A multi-agent, retrieval-augmented decision system layered over an existing ERP
for semiconductor and PCBA manufacturers.**

Read-only against the system of record. Retrieval-grounded at every stage.
Deterministic where correctness matters. No autonomous ordering.

---

## Stack at a glance

| Layer | Technology |
|---|---|
| Client | Next.js 16 (App Router) · TypeScript · oklch design tokens |
| API | FastAPI (Python) · 6 routers · server-sent events for long runs |
| Model | Groq · `openai/gpt-oss-120b` · JSON-schema constrained decoding |
| Retrieval | Structured RAG — schema-indexed, tool-invoked, guard-verified |
| Orchestration | 6 purpose-built agents, sequenced and parallelised |
| Rules | Deterministic constraint engine (no model in path) |
| Forecasting | Holt-Winters (statsmodels) |
| Document parsing | pdfplumber (table extraction) · openpyxl |
| Data | PostgreSQL 17 · psycopg3 + ConnectionPool · two schemas |
| Access control | Dedicated `scip_readonly` role · two independent locks |
| Deployment | Render (API + web) |
| Tests | pytest — 55 passing |

---

## 1. The retrieval model

CircuitMind is retrieval-augmented **throughout**, not only in the chat surface.
No agent reasons from model memory. Every stage retrieves current state from
PostgreSQL, reasons over what it retrieved, and passes structured output on.

```
                    ┌──────────────────────────────┐
   PUBLISHED        │      RETRIEVAL SUBSTRATE     │      BOM
    EVENT   ───────▶│   PostgreSQL — erp schema    │◀─────  DOCUMENT
                    │   (read-only mirror of ERP)  │
                    └──────────────┬───────────────┘
                                   │  every agent retrieves here
        ┌──────────┬───────────┬───┴────┬────────────┬──────────┐
        ▼          ▼           ▼        ▼            ▼          ▼
   Intelligence  Demand   Supply risk  Component  Procurement  Assistant
        │          │           │        │            │          │
        └──────────┴───────────┴────┬───┴────────────┘          │
                                    ▼                            ▼
                        platform schema (analysis)        answer + evidence
                                    │
                                    ▼
                    PENDING_APPROVAL → human → PO per supplier
```

**What each agent retrieves, and what actually decides:**

| Agent | Retrieves | Reasoning | Decided by |
|---|---|---|---|
| Intelligence | component catalogue, categories | LLM, schema-constrained | enum bounded by catalogue |
| Demand | committed orders, consumption history | Holt-Winters | arithmetic |
| Supply risk | inventory, open POs, lead times | running stock ledger | arithmetic |
| Component | candidate parts, board constraints | LLM proposes | **rule engine** |
| Procurement | supplier stock, prices, on-time record | ranking | arithmetic |
| Assistant | any of the above, via 10 tools | LLM selects the query | database + guard |

The pattern is constant: **retrieval is broad, generation is narrow, and the
decision is deterministic.**

---

## 2. Structured RAG — the assistant

```
user question (natural language)
        ↓
LLM selects tool + arguments        ← the retrieval step
        ↓
PostgreSQL executes the query       ← the ground truth
        ↓
rows returned to model as context
        ↓
LLM composes the answer
        ↓
output guard verifies every figure  ← the grounding check
```

**Ten read-only tools:**
`current_shortages` · `demand_forecast` · `events_affecting_inventory` ·
`find_component` · `inventory_overview` · `list_suppliers` ·
`pending_recommendations` · `stock_ledger` · `stock_position` ·
`supplier_reliability`

**Why the index is the schema.** Supply-chain answers are quantities, dates and
prices. Embedding a table and retrieving the nearest chunk returns
*approximately* the right number. Executing the query returns *the* number.
Retrieval is still the mechanism — the corpus is relational rather than textual.

**Grounding enforcement** (`agents/assistant/guard.py`):

- **BLOCK** — answer contains figures but no tool was called
- **FLAG** — a figure appears that is in no tool result
- per-turn memoisation prevents duplicate retrieval calls

**Roadmap:** pgvector + embedding retrieval for substitute-candidate generation.
It changes which candidates are *proposed*; approval stays with the rule engine.

---

## 3. Ingestion

**Events.** Extraction runs against a **JSON schema whose `category` field is an
enum generated from the live catalogue** — the model is structurally unable to
emit a class the database does not contain.

**Documents.** BOMs arrive as PDF, XLSX, CSV or TXT.

- pdfplumber table extraction with font-metric cell fitting (prevents column bleed)
- scored header-row detection, not "first non-empty row"
- text-layer probe rejects scanned PDFs explicitly rather than returning zero rows
- DNP lines preserved as quantity 0 end to end
- reference designators and title blocks excluded from part matching
- unresolved lines ranked for a human — never auto-matched

---

## 4. Deterministic rule engine

`agents/component/rules.py`. Compatibility is decided here, never by the model.

```
min_<field>          spec[field] >= value
max_<field>          spec[field] <= value
rail_voltage_v       spec.vcc_min_v <= value <= spec.vcc_max_v
ambient_temp_min_c   spec.temp_min_c <= value
ambient_temp_max_c   spec.temp_max_c >= value
required_interfaces  every listed interface present in spec.interfaces
<field>              exact match
```

Design-floor vs datasheet-ceiling alias: a design requiring `min_freq_mhz: 160`
is compared against the part's `max_freq_mhz`, because that is what a datasheet
publishes.

**Worked rejection:** LQFP144 and LQFP64 rejected against an LQFP100 land
pattern. Lexical *or* semantic similarity would rank both highly. This is the
reason retrieval and approval are separate stages.

---

## 5. Data model

**PostgreSQL 17**, two schemas — the product boundary is enforced in the schema
layout, not by convention.

`erp` *(read-only mirror of the system of record — never written)*
```
products · bom · components · suppliers · supplier_components
inventory · warehouses · customer_orders · purchase_orders
purchase_order_items · production_plans
```

`platform` *(everything the analysis produces)*
```
external_events · event_impacts · demand_forecasts · shortages
alternatives · supplier_scores · purchase_recommendations
purchase_recommendation_lines · build_requests · build_request_lines
v_stock_position
```

**Two independent access locks** on the retrieval path:
1. privilege grants on the `scip_readonly` role
2. `default_transaction_read_only` on the session

The database refuses writes even if the tool layer were wrong.

---

## 6. Decision output

```
costed plan → PENDING_APPROVAL → named human approves → PDF per supplier
```

- `MAX_LINES = 3` — buyers do not want six POs for one part
- `RISK_PREMIUM = 0.15` · `DUAL_SOURCE_PREMIUM_LIMIT = 0.05`
- suppliers touched by the event excluded before ranking
- lead times padded by recency-weighted on-time record
- each PDF carries only its own supplier's pricing — no cross-supplier leakage
- **no code path transmits an order**

---

## 7. Interfaces

**Frontend** — Next.js 16, ten routes. Request de-duplication via 8s TTL cache
and in-flight promise map, so concurrent components sharing an endpoint issue one
network call. Long pipelines consumed over SSE.

```
/  /ask  /bom  /events  /login  /recommendations
/recommendations/[id]  /runs  /shortages  /suppliers
```

**API**
```
GET  /api/health · /api/overview · /api/events · /api/impacts
GET  /api/shortages · /api/suppliers
GET  /api/recommendations · /api/recommendations/{id}
GET  /api/recommendations/{id}/po · /po.zip · /po/manifest
POST /api/recommendations/{id}/approve
POST /api/ask · /api/bom/preview
POST /api/run/news · /api/run/bom          (SSE-streamed)
```

---

## Design principles

1. Retrieval is broad. Generation is narrow. The decision is deterministic.
2. The model is never the source of a factual number.
3. Only events that have already occurred are analysed — nothing is predicted.
4. Compatibility is decided by rules, not resemblance.
5. Unknown parts are ranked for a human, never auto-matched.
6. Nothing is ordered without a named approval.
7. The ERP is read. It is never written.
