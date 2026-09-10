# CircuitMind — Handoff (new laptop)

**Purpose of this file:** paste it into a fresh LLM session (or a new Claude
Code instance) on the new laptop to restore full context without re-deriving
anything.

**Written:** 2026-09-10, end of the second working session.
**Team repo (private):** `github.com/Udyoga-Pramoda-Hackathon-2026/team-satyatma`
**Personal mirror (has every commit below):** `github.com/Abhiroop-hgv/CircuitMind`

---

## 0. READ FIRST — this is a new machine, nothing is installed

The previous sessions ran on a different Windows PC. **None of that machine's
state exists here** — no PostgreSQL cluster, no `.env`, no Python packages, no
`node_modules`, no seeded database, no generated recommendations. The database
and `.env` are **not** in the repo (`.env` is gitignored, and it must stay
that way — it holds the Groq key).

Everything has to be stood up from scratch from the repo. There is a script for
it. Do this before anything else:

### Prerequisites to install manually

| Tool | Version | Note |
|---|---|---|
| Python | 3.10+ | tick **"Add python.exe to PATH"** in the installer |
| Node.js | 20+ | LTS is fine |
| PostgreSQL | 16 or 17 | **remember the `postgres` superuser password** |
| Git | any recent | |

Reopen the terminal afterwards so `PATH` updates.

### Then

```powershell
git clone https://github.com/Abhiroop-hgv/CircuitMind.git
cd CircuitMind
Copy-Item .env.example .env
notepad .env          # set GROQ_API_KEY to a real key (console.groq.com, free tier)
pwsh scripts/bootstrap.ps1
pwsh scripts/run.ps1
```

`bootstrap.ps1` (added this session): checks the four prerequisites, creates
the `scip` role + database in the local PostgreSQL **service on 5432** (not a
hand-rolled cluster — nothing to restart after a reboot), `pip install -r
requirements.txt`, builds and seeds the dummy ERP (`init_db.py`), creates the
read-only role (`create_readonly_role.py`), runs `demo.py --offline` to
generate the canonical recommendation, then `npm install && npm run build` in
`web/`. It asks for the postgres password once.

`run.ps1` starts the API on `:8000` and the web app on `:3000`. Open
**http://localhost:3000**, sign in with any name.

Full details + failure modes: `SETUP.md` in the repo.

**Known gap:** `bootstrap.ps1` generates only **one** recommendation — the
STM32 export-licence scenario (§4). The second (BOM/flash) scenario does **not**
reproduce from a clean seed as currently scripted — see §6, issue 11.

---

## 1. What this project is

CircuitMind is an AI decision layer over an existing ERP for semiconductor and
PCBA manufacturers. It reads a **published** external event (export control,
port closure, fab incident), resolves it against the buyer's own BOM,
inventory, demand and supplier data, verifies substitute parts with
deterministic rules, and produces a costed multi-supplier procurement plan
that sits at `PENDING_APPROVAL` until a named person signs it. It is **not**
an ERP — no order entry, no invoicing, read-only against the system of
record.

Built for **Yukti Manthan 2.0**, an AI hackathon, by **Team Satyatma**
(Abhiroop, Vishnu, Aravind, SreePhaneesh, Shruthi). Mentors: Pushkar, Vishal.

One-line pitch: **"The model chooses which question to ask. The database
answers it."** Tagline used in the deck/video: **"From disruption to
decisions."**

---

## 2. Tech stack

| Layer | Technology |
|---|---|
| Database | PostgreSQL 17, two schemas, raw SQL via psycopg 3 (`psycopg[binary,pool]`) |
| API | FastAPI, uvicorn, server-sent events for long-running pipelines |
| Language model | Groq, `openai/gpt-oss-120b`, JSON-schema constrained decoding, called by plain `requests`/`httpx` to `https://api.groq.com/openai/v1` (no SDK) |
| Forecasting | statsmodels — Holt-Winters exponential smoothing |
| BOM parsing | pdfplumber (tables), pypdf, openpyxl |
| Frontend | Next.js 16 (App Router), TypeScript, plain CSS, oklch tokens |
| Tests | pytest (~55 tests; not re-run this session) |
| Deployment (intended) | Render, both halves |

**Correction to the earlier handoff:** `anthropic>=0.40` in `requirements.txt`
is **not vestigial**. It is a real lazy import in
`agents/intelligence/agent.py` and `agents/intelligence/extract.py` — the
non-Groq extraction path. Offline runs (`FixtureExtractor`) don't need it, but
it's a live optional dependency. Leave it in.

---

## 3. Architecture

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

Plus a sixth surface not in that chain: **Ask**, a tool-calling assistant
(`agents/assistant/`) with 10 read-only tools over the same tables.

### Two-schema database boundary

- **`erp`** — read-only mirror of the system of record: `products`, `bom`,
  `components`, `suppliers`, `supplier_components`, `inventory`,
  `warehouses`, `customer_orders`, `purchase_orders`,
  `purchase_order_items`, `production_plans`. Never written by the app.
- **`platform`** — everything the analysis produces: `external_events`,
  `event_impacts`, `demand_forecasts`, `shortages`, `alternatives`,
  `supplier_scores`, `purchase_recommendations`,
  `purchase_recommendation_lines`, `build_requests`, `build_request_lines`,
  `v_stock_position` (view). `shortages` also has `build_request_id` (nullable)
  linking a shortage to a BOM build rather than an event.

### The invariants (do not violate these in any change)

1. The model is never the source of a factual number — every figure traces
   to a database query.
2. Only events that have **already happened** are analysed. Nothing is
   forecast except ordinary demand (Holt-Winters).
3. Compatibility is decided by a deterministic rule engine
   (`agents/component/rules.py`), never by the model. Similar part numbers
   are not treated as compatible.
4. Unknown BOM parts are ranked for a human, never auto-matched.
5. Nothing is ordered without a named human approval. No code path
   transmits a purchase order.
6. The assistant connects as `scip_readonly` — two independent locks
   (privilege grants + `default_transaction_read_only`).

### Repo layout

```
agents/{intelligence,demand,supply_risk,component,procurement,assistant,bom_intake}/
api/{main,config,serialization,streaming,pipeline}.py
api/routers/{health,catalogue,recommendations,assistant,runs,bom}.py
db/{connection,schema.sql,seed_master.sql,seed_orders.py,migrations/}
scripts/       demo, seeding, reset, sample-BOM generators, bootstrap.ps1, run.ps1
tests/         conftest, test_rules, test_parser, test_guard_and_intake
web/src/app/   / /ask /bom /events /login /recommendations
                /recommendations/[id] /runs /shortages /suppliers
artifacts/     decks, scripts, architecture diagram, video script, mock POs
SETUP.md       from-scratch setup guide (added this session)
```

### HTTP surface

```
GET  /api/health · /api/overview · /api/events · /api/impacts
GET  /api/shortages · /api/suppliers
GET  /api/recommendations · /api/recommendations/{id}
GET  /api/recommendations/{id}/po · /po.zip · /po/manifest
POST /api/recommendations/{id}/approve
POST /api/ask · /api/bom/preview
POST /api/run/news · /api/run/bom          (SSE-streamed)
```

### Key constants

- `TODAY` pinned to `2026-09-03` in `api/config.py`
- `WATCH_MPN = "STM32F407VGT6"`
- `RISK_PREMIUM = 0.15`, `DUAL_SOURCE_PREMIUM_LIMIT = 0.05`, `MAX_LINES = 3`
- RNG seed fixed in `db/seed_orders.py` — `init_db.py` reproduces identical
  numbers every run.

---

## 4. Canonical demo scenario — reproduces cleanly

After `bootstrap.ps1` (i.e. `demo.py --offline`), one recommendation exists.
Verified this session, numbers identical to every earlier run:

> An export licence notice hits **STM32F407VGT6**, used on the **MC-3000**
> and **SD-220** boards. Coverage leaves **5,130 units short by 15 October**.
> **STM32F429VGT6** clears the rule engine as a substitute; two look-alikes are
> rejected on footprint — **STM32F429ZIT6** (LQFP-144) and **STM32F405RGT6**
> (LQFP-64) against the board's **LQFP-100** land pattern. Procurement splits
> the buy three ways, weighted by on-time record:

| Supplier | Units | Unit price | Line total | Arrives |
|---|---|---|---|---|
| Avnet Asia Pte Ltd | 3,000 | $11.05 | $33,150.00 | 15 Sep |
| DigiKey Electronics | 2,000 | $11.20 | $22,400.00 | 10 Sep |
| Mouser Electronics | 130 | $10.85 | $1,410.50 | 22 Sep |

**Total: 5,130 units, $56,960.50, landed 23 days early.** Status:
`PENDING_APPROVAL`. (The recommendation's `id` increments each time `demo.py`
runs — it was #1 originally, #8 after this session's resets. The demo just
opens whatever pending recommendation is current.)

### Second scenario (BOM / flash substitution) — DOES NOT reproduce cleanly

Intended story: the Sensor Hub **SH-100** board reassessed at a high build
quantity; the flash chip can't be sourced in full from unaffected suppliers, so
CircuitMind swaps to a **verified alternative** — mirroring #1's "different part"
shape but triggered by a BOM instead of a news event.

This session got it working on the old machine at build-qty 8,500
(MX25L12835FM2I-10G → **W25Q128JVSIQ**, ~$19,667.55). **But on a fresh seed the
SH-100 BOM resolves its flash line to W25Q128JVSIQ directly**, so
`scripts/make_bom_split_po.py` (which hunts for `FEATURED_MPN =
"MX25L12835FM2I-10G"`) finds nothing and errors "not short at this quantity".
The scenario script needs reworking — see §6 issue 11.

Recommendation for the **500 ceramic capacitors** ($4.70, sometimes `APPROVED`)
is a stray from `bom_scenario.py` testing. Cosmetic clutter on the
Recommendations list; delete if it reappears.

---

## 5. What changed in this session (all pushed to `Abhiroop-hgv/CircuitMind`)

Branch pushed as `main` on the personal mirror. Local branch name:
`circuitmind-session-updates`. Tip: `1d8ee01`.

| Commit | Change |
|---|---|
| `0aaf4ba` | **Demand-forecast "not applicable" fix.** A build-request recommendation has no Holt-Winters forecast (no order history for a new-product board). The detail page showed a bare "no forecast has been run", which read as a bug. `api/routers/recommendations.py` now returns `build_request_id` / `build_sku` / `build_name` / `build_qty` on the shortage; `web/src/app/recommendations/[id]/page.tsx` explains the requirement comes from the stated build quantity. `web/src/lib/api.ts` type updated. |
| `2d409eb` | **CircuitMind logo** added — `web/public/circuitmind-logo.png`, used in the sidebar (`Shell.tsx`), the sign-in pitch page (`login/page.tsx`), and as the favicon (`layout.tsx`). `globals.css` uses `mix-blend-mode: multiply` to drop the logo's white plate onto the panel. **Not visually confirmed** — the sidebar size in particular was never eyeballed on a working display. |
| `a1f0dd3` | **Session artifacts committed** — `artifacts/3min-Video-Script.md` (see §7), `Technical-Architecture.md`, `Dark-Friday-Pitch-Script.md`, `artifacts/mock-purchase-orders/`, `scripts/make_bom_split_po.py`, `scripts/make_mixed_bom_xlsx.py`, `samples/MC-3000_RevD_BOM.xlsx`, `MASTER_PROMPT.md`, `.claude-handoff.md`. |
| `282b035` | **Recommendation header leads with the outcome, not the part code.** The hero line was `MX25L12835FM2I-10G — short 7,000 units…`; now `Short 7,000 units from 15 November — a verified alternative part is ready to drop in` (when `requires_bom_change`) or `…covered in full by the original part, no design change`. Also **fixed a hardcoded bug**: `boards = ["MC-3000", "SD-220"]` for *every* recommendation → now derived from `data.alternatives[].checks[].board`, falling back to `shortage.build_sku`. |
| `be982bb` | **BOM scenario script** — default `--build-qty` 7000 → 8500 (so procurement swaps to the verified alternative rather than multi-sourcing the original), and the script now deletes the stray shortages BuildabilityAgent writes for every other blocked line on the board (the "21 stray rows" bug from the last handoff). *Note: this fix is moot until issue 11 is resolved.* |
| `1d8ee01` | **From-scratch setup** — `SETUP.md`, `scripts/bootstrap.ps1`, `scripts/run.ps1`. Targets the PostgreSQL **service on 5432**, not a hand-rolled `initdb` cluster on 5433 — so there is nothing to restart after a reboot (resolves the old handoff's issues 3 and 4). |

### Also done this session (not code)

- **3-minute video script** written (`artifacts/3min-Video-Script.md`) to the
  organiser's timing table (0:00 opening … 2:52 close), covering all three
  capabilities (event resolution, BOM intake, Ask). A plain-language version
  for a non-technical audience was also produced (in chat, not filed).
- Confirmed the STM32 demo numbers against the live app: $56,960.50, 3-way
  split 3,000 / 2,000 / 130, rejected alternatives STM32F429ZIT6 (LQFP-144)
  and STM32F405RGT6 (LQFP-64).
- Diagnosed "slow screen transitions" → it was Next.js **dev-mode
  compilation** (`/recommendations/[id]` took 11 s on first visit). Fixed by
  running the **production build** (`npm run build && npm start`) instead of
  `npm run dev`. `bootstrap.ps1` builds; `run.ps1` runs `npm start`.
- Diagnosed "slow PO generation after approve" → **not actually slow**
  (measured: click-to-PO-links 350 ms, each PDF < 200 ms). The perception was
  the dev-mode compile above, plus PO links being `target="_blank"` so the
  browser opens its PDF viewer in a new tab.

---

## 6. Outstanding issues

1. **Second BOM scenario doesn't reproduce from a clean seed** (issue 11
   below is the same thing, kept here for prominence). The canonical STM32
   demo is fine; the flash-substitution story is not, as scripted.
2. **Team repo is private.** Named on slide 1 of two decks. Make public or
   add judges. The personal mirror `Abhiroop-hgv/CircuitMind` is separate —
   decide which one the submission points at.
3. **Render deployment** — state unknown from here; last handoff said its one
   recommendation showed `APPROVED`. If judges use the live link, reset it
   (`scripts/reset_approval.py` against Render's `DATABASE_URL`).
4. **Recommendation #2 (stray $4.70 capacitor)** sometimes present and
   `APPROVED`. One-line `DELETE` if it clutters the demo.
5. **Dashboard headline shortage ordering** — the overview banner surfaced the
   BOM story ahead of the STM32 one. Likely the `ORDER BY` in the
   `/api/overview` query. Not investigated this session.
6. **Ideation deck slide 6** still shows wireframes branded "SupplyChain
   Sentinel" (old name) rather than real screenshots.
7. **No `CLAUDE.md`** — a `/init` was requested two sessions ago and never
   finished.
8. **Logo not visually finalised** — committed and wired in, but the sidebar
   size / blend was never checked on a working display. Look at it once the
   app is running on the new laptop; adjust `.mark-logo` / `.brand-logo` in
   `web/src/app/globals.css` if needed, then `npm run build`.
9. **~55 pytest tests not re-run this session** — run `python -m pytest`
   after bootstrap to confirm nothing regressed.
10. **Local `main` was 1 commit behind team `origin/main`** on the old
    machine and never merged. The personal mirror was pushed from the
    session branch (which contains all of local `main` + the six commits
    above) — so the personal mirror is missing that one upstream commit.
    Reconcile if it matters.
11. **`scripts/make_bom_split_po.py` assumes the SH-100 flash MPN is
    `MX25L12835FM2I-10G`.** On a fresh seed the BOM resolves that line to
    `W25Q128JVSIQ` instead, so the script errors. Fix options: (a) point
    `FEATURED_MPN` at `W25Q128JVSIQ` and pick a different verified alternative
    for it, (b) edit the SH-100 sample BOM so the flash line resolves to
    Macronix, or (c) feature a different SH-100 part entirely for the second
    scenario. Whatever the choice, re-verify end to end and update §4.

---

## 7. The 3-minute video script

`artifacts/3min-Video-Script.md` — mapped to the organiser's timing table,
five speakers, demo block covers event resolution + BOM intake + Ask. Demo
figures in it are marked "verify against the live app before recording"
because the flash scenario (issue 11) may change. The STM32 numbers in it are
correct.

---

## 8. Explicit next steps (priority order)

1. On the new laptop: install prerequisites → clone → set `GROQ_API_KEY` →
   `pwsh scripts/bootstrap.ps1` → `pwsh scripts/run.ps1` → confirm
   http://localhost:3000 shows the STM32 recommendation.
2. `python -m pytest` — confirm the suite still passes (issue 9).
3. Fix the second BOM scenario so it reproduces (issue 11), then re-verify
   §4 and the video script's second-scenario numbers.
4. Eyeball the logo; adjust CSS if needed (issue 8).
5. Decide public/private + which repo the submission cites (issues 2, 10).
6. Reset the Render deployment if it's part of the submission (issue 3).
7. Write `CLAUDE.md` (issue 7).
8. Replace deck slide 6 wireframes with real screenshots (issue 6).
9. Investigate the overview-banner ordering (issue 5).
