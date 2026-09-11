# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CircuitMind is an AI decision layer that sits **on top of** a mirrored ERP. It reads a
published external event (or a new board's BOM), resolves it against the buyer's own
parts/inventory/orders/suppliers, verifies substitute parts with a deterministic rule
engine, and produces a costed multi-supplier procurement plan that waits at
`PENDING_APPROVAL` until a named person signs it. It is not an ERP — read-only against
the system of record, and no code path transmits a purchase order.

`ARCHITECTURE.md` is the full reference (every agent, table, and decision). `README.md`
has the worked example with real numbers.

## Invariants — do not break these in any change

1. **The model reads; the code decides.** Every quantity, price, lead time, date, and
   compatibility verdict traces to a database row or a reproducible calculation. The
   language model only turns prose into values the DB already understands. Enforced three
   ways: JSON-schema `enum` constrained decoding (`agents/intelligence/`), the
   `scip_readonly` Postgres role for the assistant, and an output guard that replaces/flags
   un-sourced figures.
2. **Only events that have already happened are analysed.** Nothing is forecast except
   ordinary demand (Holt-Winters, `agents/demand/`).
3. **Compatibility is decided by `agents/component/rules.py`**, never the model. Similar
   part numbers are not treated as compatible.
4. **Unknown BOM parts are ranked for a human, never auto-matched.**
5. **Nothing is ordered without a named human approval.**

## Two-schema database boundary

One PostgreSQL database, two schemas, `search_path = erp, platform, public`:

- **`erp.*`** — read-only mirror of the system of record (products, bom, components,
  suppliers, supplier_components, inventory, warehouses, customer_orders,
  purchase_orders, production_plans). The app never writes here. BOM intake is the one
  exception: registering a new board writes `erp.products` + `erp.bom`.
- **`platform.*`** — everything the analysis produces (external_events, event_impacts,
  demand_forecasts, shortages, alternatives, supplier_scores, purchase_recommendations,
  purchase_recommendation_lines, build_requests, build_request_lines, `v_stock_position`).

`db/connection.py`: `connect()` = one fresh connection (CLI scripts); `pooled()` = pooled
(the API). Raw SQL via psycopg 3, no ORM.

## Commands

If a `.venv/` exists in the repo root, use `.venv/Scripts/python.exe` (Windows) /
`.venv/bin/python` for every Python command below — the system `python` may be a version
without wheels for numpy/scipy/statsmodels.

```bash
# database: schema + deterministic seed (safe to re-run, rebuilds from scratch)
python scripts/init_db.py
python scripts/verify.py                 # confirms the seeded numbers hold
python scripts/create_readonly_role.py   # writes DATABASE_URL_RO into .env

# the whole agent chain in the terminal, no UI
python scripts/demo.py --offline         # fixtures, no network  -> recommendation #1 (STM32)
python scripts/demo.py --scenario both   # news event, then a BOM landing into it

# API (:8000) and dashboard (:3000)
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
cd web && npm install && npm run build && npm start   # NOT `npm run dev` — see below

# tests
python -m pytest                         # 55 tests
python -m pytest tests/test_parser.py -k title_block   # a single test

# put an approved demo back to PENDING for a re-run
python scripts/reset_approval.py
```

Windows convenience wrappers: `pwsh scripts/bootstrap.ps1` (one-shot setup) and
`pwsh scripts/run.ps1` (start both servers). `SETUP.md` covers from-scratch install.

Run the dashboard with `npm run build && npm start`, not `npm run dev` — dev-mode
compiles routes on first visit (~10 s for `/recommendations/[id]`), which reads as the
app being slow.

## Where things live

- `agents/{intelligence,demand,supply_risk,component,procurement,assistant,bom_intake}/` —
  one directory per stage; each stage's output is the next one's input. `assistant/` is a
  separate tool-calling surface (10 read-only tools) reached via `POST /api/ask`.
- `api/main.py` is assembly only. Endpoints live in `api/routers/` grouped by subject;
  `api/config.py` holds values the whole API agrees on — `TODAY` is pinned to
  `2026-09-03`, `WATCH_MPN = "STM32F407VGT6"`, and the procurement constants
  (`RISK_PREMIUM`, `DUAL_SOURCE_PREMIUM_LIMIT`, `MAX_LINES`). `api/streaming.py` is the SSE
  plumbing for `/api/run/*`; `api/pipeline.py` is the shared tail both pipelines end in.
- `db/schema.sql` + `db/seed_master.sql` + `db/migrations/` (applied in order by
  `init_db.py`); `db/seed_orders.py` generates orders/POs from a **fixed RNG seed**, so
  `init_db.py` reproduces identical numbers every run.
- `scripts/` — demo, seeding, reset, sample-BOM generators. `scripts/make_bom_split_po.py`
  generates the second demo recommendation (SH-100 flash substitution) and needs the
  SH-100 build_request to exist first (`scripts/run_bom_intake.py`).
- `web/` — Next.js 16 App Router, TypeScript, plain CSS with oklch tokens in
  `src/app/globals.css` (light theme only). **Read `web/AGENTS.md` before editing web code**
  — it is Next.js 16 with breaking changes from older versions.
- `tests/` — pytest. Every parser test is a bug that actually happened; they are
  regression pins, not coverage.
- `integration/circuitmind/` — a drop-in replacement for the sister project's
  `compatibility_score()`; do not couple it to this repo's internals.
- `render.yaml` + `RENDER.md` — Render Blueprint (Postgres + API + web) and the
  deploy walkthrough. `CORS_ORIGINS` (API) and `NEXT_PUBLIC_API` (web) carry the
  two services' URLs into each other — never hardcode a deployment's URL in
  source, as `api/main.py` once did.

## Language model

Groq, `openai/gpt-oss-120b`, called by plain `requests`/`httpx` to
`https://api.groq.com/openai/v1` — no SDK. `GROQ_API_KEY` in `.env` (gitignored, must stay
that way). Offline runs use `FixtureExtractor` and need no key. `anthropic>=0.40` in
`requirements.txt` is a live optional dependency (the non-Groq extraction path in
`agents/intelligence/agent.py` / `extract.py`), not vestigial.

## Demo data

Fabricated, deterministic: 5 boards, 30 components, 10 suppliers, 451 customer orders,
132 closed POs (with receipt dates — that is what makes supplier scoring possible), 7
external events (all `is_synthetic`, all `example.invalid` URLs). The pipeline analyses
only the one event that resolves to a supplier lane or country of origin actually bought
from; what it declines to act on is part of the point.
