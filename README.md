# Supply-Chain Intelligence Layer

> ERP tells you what you have. External intelligence tells you what is changing.
> This connects the two and tells you what to do.

An AI decision layer that sits **on top of** an existing ERP. It is not an ERP,
and it never becomes one. The ERP stays the system of record; we read from it,
combine it with what is happening in the outside world, and recommend an action
that a human approves.

## Status

**Stage 1 of the build: the dummy ERP database.** Nothing else exists yet — no
agents, no API, no frontend. That is deliberate. Every agent reads from these
tables, so the numbers here have to be right before anything is built on them.

## Layout

```
db/
  schema.sql        DDL. Two schemas: erp (dummy mirror) and platform (ours)
  seed_master.sql   hand-written reference data the demo arithmetic depends on
  seed_orders.py    generated volume: order history, inventory, supplier offers
  pgvector.sql      OPTIONAL, applied later for the component agent only
  connection.py     the one place the connection string is resolved
scripts/
  init_db.py        drop, recreate, load everything
  verify.py         proves the data supports the demo, in plain SQL
```

## Setup

This project runs its **own** PostgreSQL instance on port **5433**, separate
from the PostgreSQL 17 Windows service on 5432. That was not the original plan —
the superuser password for the existing service was not recoverable, so rather
than reset it we used the installed binaries to `initdb` a fresh instance we
fully control. It turned out to be the better arrangement anyway: the demo
database is disposable, isolated, and needs no admin rights.

- data directory: `C:\Users\DELL\.scip-pgdata` — deliberately **not** under
  OneDrive; never let a sync client touch a live Postgres data directory
- auth: `trust`, bound to `127.0.0.1` only. Fine for a throwaway demo instance
  on a non-standard port holding nothing but fabricated data. Do not copy this
  arrangement anywhere real.
- the instance is **not** a Windows service, so it does not survive a reboot

Day to day:

```bash
# after a reboot -- use the absolute path, and the per-process policy bypass
# (this machine blocks .ps1 by default; do not weaken that setting globally)
powershell -ExecutionPolicy Bypass -File "C:\Users\DELL\OneDrive\Desktop\supply-chain-intel\scripts\pg_start.ps1"

python scripts/init_db.py                 # rebuild from scratch, any time
python scripts/verify.py                  # check the numbers still hold
```

Start it from **your own** terminal, not from a tool session — the server dies
with whatever process launched it. If that happens, Postgres does crash recovery
on the next start (~40 seconds of `rejecting connections`) and loses nothing.
Worst case, `init_db.py` rebuilds the whole thing in seconds; the database is
disposable by design.

First-time-only, already done: `initdb -D C:\Users\DELL\.scip-pgdata -U scip
--auth=trust`, then `createdb -p 5433 -U scip scip`, then `cp .env.example .env`
with `DATABASE_URL=postgresql://scip@127.0.0.1:5433/scip`.

`docker-compose.yml` is kept as an alternative (`pgvector/pgvector:pg16`, also on
5433) for machines that have Docker. This one does not.

## The two schemas

| schema | what it is | who writes it |
|---|---|---|
| `erp` | a dummy mirror of what SAP / Oracle / Dynamics would expose | nobody — read-only to us |
| `platform` | external events, and later agent output | us |

The split is the product boundary made visible in code. In a real deployment
the `erp` schema is replaced by a connector and **nothing else changes**. There
is deliberately no order entry, no goods receipt, no invoicing, no accounting,
no warehouse execution. We are not rebuilding an ERP.

## The story the data encodes

`scripts/verify.py` walks this end to end. All figures are for a 60-day horizon
from 2026-09-03.

```
Export licence requirement on MCU/logic ICs shipping from China (event 1)
  -> Shenzhen Ruiyang Semiconductor, Fujian Longtai Electronics  (suppliers in China)
  -> STM32F407VGT6                                               (what they supply us)
  -> MC-3000 Motor Controller, SD-220 Servo Drive                (boards that use it)

  committed demand   10,000     6,500 x MC-3000 + 3,500 x SD-220, 1 MCU each
  usable stock        6,000     7,700 on hand - 1,200 reserved - 500 safety
  open PO PO-2026-0187  4,000   from Shenzhen Ruiyang, due 2026-09-28, ex-China
  ------------------------------
  baseline gap            0     nothing is flagged today
  gap if that PO is held -4,000 <- the shortage the system has to find
```

The substitution then has to be earned, not asserted. Five MCUs sit in the
catalogue as candidates, and MC-3000's `design_constraints` separate them:

| candidate | outcome against MC-3000 |
|---|---|
| STM32F429VGT6 | passes — same footprint and pinout family, more RAM |
| STM32F407VGT7 | passes — same part, wider temperature grade, costs more |
| GD32F407VGT6 | passes technically — but is *only* sourceable from the affected region |
| STM32F429ZIT6 | fails — LQFP-144, wrong footprint |
| STM32F405RGT6 | fails — LQFP-64, 51 I/O against a 78 I/O requirement |

Three more substitution pairs are seeded the same way (CAN transceiver,
Ethernet PHY, LDO) so the component agent has more than one case to prove
itself on.

Only the incumbent's **Chinese** suppliers hold volume — the Western
distributors carry 300–800 pieces against a 4,000 shortfall. That is the whole
reason an alternative is needed rather than just another purchase order.

## Decisions worth knowing

- **`bom.design_constraints` is the compatibility gate, not the incumbent's
  datasheet.** A replacement is judged against what the *board* requires. The
  same STM32F407VGT6 carries a stricter requirement on MC-3000 (85 °C, 78 I/O)
  than on SD-220 (70 °C, 70 I/O) — so compatibility is per design, not per part.
- **`external_events.extracted` is left empty by the seed.** Filling it is the
  Intelligence Agent's job. Pre-computing it would mean the demo secretly knows
  the answer, and we would learn nothing about whether the agent works.
- **Every seeded event is flagged `is_synthetic = TRUE`** and carries an
  `example.invalid` URL. None of them is a real published report. The two
  suppliers the disruption story touches are fictional companies on purpose — we
  do not attach an invented trade-restriction narrative to a real named company.
  Real distributor names appear only as realistic labels; every price, stock
  figure and lead time in this database is fabricated.
- **The seed is deterministic** (`RNG_SEED = 20260903`), so the demo tells the
  same story on every run.
- **Noise is seeded on purpose.** Four of the seven events are irrelevant to
  this company. An intelligence agent that reacts to all seven is not working.
- **Exactly one shortage exists.** Every other component is stocked to 1.6×
  horizon demand, so the demo shows one clean signal rather than a wall of red.
- **The China exposure is broad on purpose.** Nineteen supplier/component/product
  combinations touch a Chinese supplier — connectors, TVS diodes, a buck
  regulator, the ESP32 module. Only a handful are microcontrollers. Narrowing
  "China is involved in 19 things we buy" down to "one of them actually creates
  a shortage" is the Intelligence Agent's real work; if the seed made China
  touch exactly one part, the agent would look clever without doing anything.
- **pgvector is not a dependency yet.** Everything up to the Supply Risk Agent
  runs on plain Postgres; `db/pgvector.sql` gets applied when retrieval is
  actually needed.

## Stage 2 — the Intelligence Agent

`agents/intelligence/` — answers *"does this event matter to us, and to what
exactly?"* It does not size shortages and it does not decide purchases.

```
event -> extract (LLM) -> match (SQL) -> score (rules) -> persist -> explain (LLM)
```

| file | job | LLM? |
|---|---|---|
| `schema.py` | the structured reading the model must produce | — |
| `extract.py` | article -> that structure | **yes** |
| `match.py` | that structure -> our suppliers, parts, boards, POs | no |
| `score.py` | exposure rule table | no |
| `agent.py` | orchestration, persistence, the human-readable sentence | yes (sentence only) |

Run it:

```bash
python scripts/run_intelligence.py --offline --reset   # fixtures, no API key
python scripts/run_intelligence.py --reset             # real model
```

The model is shown the article and our category vocabulary, and nothing else —
no inventory, no supplier list, no quantities. It cannot invent a fact about our
business because it is never given one. Every number downstream comes from a
join you can run by hand.

**Result on the seeded feed:** 7 events in, 1 with company-specific impact.
`STM32F407VGT6` flagged HIGH — 4,000 units on PO-2026-0187, treat as ~42 days
late. The other six are rejected for four different reasons (not a physical
supply event ×3, no category of ours named, no supplier in the affected
geography), which is the discrimination the agent exists to do.

`--offline` swaps only the two language steps for hand-written fixtures in
`agents/intelligence/fixtures/`. Matching and scoring run exactly as they do for
real, and rows written that way are tagged `extractor = 'fixture'` so a fixture
run can never be mistaken for a model run.

### Two ways an event reaches a part

`match.py` runs two matching paths, and `event_impacts.match_basis` records which
one fired. They mean different things and need different arithmetic:

| basis | meaning | what is exposed |
|---|---|---|
| `SUPPLIER_LANE` | our supplier sits in the affected place | goods **in transit** from them |
| `PART_ORIGIN` | the part is **made** there, whoever sells it | **replenishment**, not shelf stock |
| `BOTH` | both of the above | both |

The origin path was a real gap for a while: the Japan MLCC fire produced *no
impact at all*, because none of our suppliers is Japanese — even though two
Murata capacitors on all four boards carry `country_of_origin = 'Japan'` and are
bought through Western distributors. Buying through Mouser does not move the fab.

It now reports:

```
[MEDIUM] GRM188R71H104KA93D  (CAPACITOR_MLCC)  via made in Japan
         boards   : IG-500, MC-3000, PI-750, SD-220
         from     : no supplier of ours there -- exposure is at the fab
         in flight: 0 units
         rule     : made there -- replenishment at risk, but 1 catalogued
                    part in this category comes from elsewhere
```

Note what it does **not** claim. `at_risk_qty` stays 0, because goods already in
transit were built before the fab stopped — delaying them would be wrong. The
handoff says *replenishment at risk* rather than *treat these POs as late*, and
the risk level turns on whether the catalogue holds a same-category part from a
different origin. Here it does — the Samsung `CL10B104KB8NNNC` — so MEDIUM
rather than HIGH.

### Reading the articles

Three interchangeable readers behind one interface, chosen by a flag:

```bash
python scripts/run_intelligence.py --groq --reset       # hosted, openai/gpt-oss-120b
python scripts/run_intelligence.py --local --reset      # Ollama on this machine
python scripts/run_intelligence.py --offline --reset    # fixtures, no network
python scripts/run_intelligence.py --groq --only EVT-2026-09-02-001   # 4s, one call
```

Groq's free tier gives 1,000 requests/day and **8,000 tokens/minute**. One event
costs roughly 1,000 tokens, so a seven-event run sits on the per-minute ceiling
and takes four backoff waits to get through. Fine as a batch job; do not run all
seven live in front of an audience. Explanations are off by default — they
quadruple the run time and the numbers carry the story alone.

Local inference does **not** work on this machine: 7.8 GB RAM with ~400 MB free
means `llama-server` cannot load a 3B model and emits `@@@@@` instead of failing
cleanly. The code is correct; the hardware is not there.

## Stage 3 — the Supply Risk Agent

`agents/supply_risk/` — takes agent 1's handoff and answers *"do we actually run
out, how many, and from when?"* **No language model anywhere in this agent.**

```bash
python scripts/run_supply_risk.py            # the numbers
python scripts/run_supply_risk.py --ledger   # the numbers, with the working
```

It does not subtract supply from demand. It runs a **stock ledger**: open at
usable stock, walk the horizon date by date, subtract each customer order as it
falls due, add each PO as it lands, and take the lowest the balance ever reaches.
Timing is the whole point — demand and supply can balance across a quarter while
you still run dry in week seven, because the parts arrive after the boards were
due. A single subtraction cannot see that.

A flagged PO has its date pushed out by the delay; if that puts it past the
horizon it stops counting as supply. A flagged PO with no stated delay is
assumed to miss — we will not invent a duration, and missing is the conservative
reading.

Result on the seeded data:

```
committed demand                    10,000
usable stock                         6,000
incoming, pushed past the horizon   -4,000   not counted
expected supply                      6,000

without the disruption, short            0   <- nothing would have been flagged
WITH the disruption, short           4,000   [CRITICAL]
first short on                  2026-10-22
```

That date is computed, not chosen: it is the day order `SO-202609-00436` for
1,102 MC-3000 boards takes the running balance below zero. `PO-2026-0187` still
arrives — on 2026-11-09, eighteen days after the line has already stopped.

Every row of that ledger is stored in `platform.shortages.ledger`, so a buyer
can check the arithmetic instead of trusting it.

**Known limitation:** demand is the committed order book only. The forecast from
agent 2 does not exist yet, so demand is understated further out.

## Stage 4 — the Component Intelligence Agent

`agents/component/` — takes `STM32F407VGT6, 4,000 units, needed by 2026-10-22`
and finds a part that can actually go on the board. **No language model.**

```bash
python scripts/run_component.py            # verdicts
python scripts/run_component.py --checks   # every check, required vs actual
```

Two stages, kept apart deliberately:

- **retrieve** — narrow the catalogue to a handful worth checking. Cheap, fuzzy,
  allowed to be wrong; a bad candidate costs one dictionary lookup.
- **verify** — decide. Deterministic rules against `bom.design_constraints`.
  Never fuzzy, because the output goes on a board.

Retrieval today is a SQL filter on category. With 30 parts that *is* the
retrieval — pgvector at this scale would be theatre, and it is not installed
here. `retrieve()` has a narrow signature so a vector implementation drops in
unchanged when the catalogue is big enough to need one.

**A part must satisfy every board that fits it.** The STM32F407VGT6 is on the
MC-3000 (85 °C, 78 I/O, 160 MHz, USB OTG) and the SD-220 (70 °C, 70 I/O,
120 MHz, no USB). Their requirements differ, so a candidate clearing only the
looser one is not a replacement.

```
[PASS] GD32F407VGT6    GigaDevice       $ 5.95  fit 100%
       SOURCING RISK: only available from suppliers this event affects
[PASS] STM32F429VGT6   STMicro          $10.85  fit 100%
       19,500 units across 5 unaffected suppliers
[PASS] STM32F407VGT7   STMicro          $13.40  fit 100%
[FAIL] STM32F429ZIT6   footprint_id -- needs LQFP100_14X14_P050, has LQFP144_20X20_P050
[FAIL] STM32F405RGT6   footprint_id -- wrong package; also io_count, pinout_family
```

Rejections are stored, not discarded. *"We checked the STM32F429ZIT6 and
rejected it because the footprint is LQFP-144"* is a far stronger claim than
silently returning one answer, and it is the first thing an engineer asks.

**Naming convention, no code changes needed.** Constraint keys are interpreted
by prefix: `min_x` / `max_x` become numeric bounds, `rail_voltage_v` must sit
inside the part's `vcc_min_v`–`vcc_max_v` window, `required_interfaces` must be
a subset, anything else is an exact match. One alias rule earns its keep: a
board's `min_freq_mhz` is checked against the part's `max_freq_mhz`, because a
design floor is compared against a datasheet ceiling. Getting that wrong failed
every MCU on the first run.

## Stage 5 — the Procurement Agent

`agents/procurement/` — turns the gap and the verified alternatives into a
purchase recommendation. **No language model. No order is ever placed.**

```bash
python scripts/run_procurement.py                      # build it
python scripts/run_procurement.py --approve "A Sujay"  # the human gate
```

It answers three questions in order, and the order is the interesting part:

1. **Can we avoid touching the BOM?** Substituting a fitted part means
   re-qualification and PCB verification, so the original wins even at a higher
   unit price — if it is obtainable from suppliers the event did not touch.
2. **If not, how far does the original get us?** Here: 1,550 of 4,000. A
   substitution is unavoidable, and the recommendation says so in those words.
3. **Once we are swapping anyway, buy the whole quantity the best way.** There
   is no partial credit for using some of the old part, and two part numbers on
   one build is worse than one.

Then, among plans that work, a stated rule: single-sourcing is usually cheapest,
and concentration is exactly what caused this shortage. So the split is costed
too and taken when the premium is under `DUAL_SOURCE_PREMIUM_LIMIT` (5%).

```
options costed:
  original part, no BOM change                          short 2,450
  switch to STM32F429VGT6, lowest cost     $ 43,400.00  covers it
  switch to STM32F407VGT7, lowest cost                  short 2,200
  switch to STM32F429VGT6, dual sourced    $ 43,720.00  covers it   <- recommended

  Mouser Electronics   STM32F429VGT6   2,400  10.85  26,040.00  2026-09-18 (15d)
  Avnet Asia Pte Ltd   STM32F429VGT6   1,600  11.05  17,680.00  2026-09-15 (12d)
  total                                       43,720.00  all in by 2026-09-18
```

The split costs **0.7% more** than single-sourcing and removes the single point
of failure. Both figures are printed, so the trade-off is arguable rather than
asserted.

### Supplier reliability

```bash
python scripts/run_reliability.py --history
```

A quoted lead time is a promise. `erp.purchase_orders.actual_receipt_date` says
what actually happened, across 126 closed POs and 18 months, and two numbers come
out of it:

- **score** (0–1) — recency-weighted share of deliveries that hit the promised
  date, decaying 8% per delivery going back. Adjusts the *price* ranking:
  `adjusted = quote × (1 + (1 − score) × 0.15)`.
- **lead-time padding** — `(1 − score) × avg days late`, added to the quoted lead
  time before asking "can this arrive in time?". This is where reliability
  actually bites: a padded lead time can miss the need-by date and drop the
  supplier entirely, not merely down-rank it.

It changes the answer:

```
                 quote    score    adjusted    allocated
Mouser          $10.85     0.53      $11.62      5,000 -> 130
Avnet           $11.05     1.00      $11.05        130 -> 3,000
DigiKey         $11.20     1.00      $11.20          0 -> 2,000
```

Mouser is cheapest on paper and hits its date 6 times in 13. The plan now costs
**$1,274 more** and buys from suppliers who deliver. Scores are recomputed from
the PO history on every run, never incremented by hand — a supplier who improves
pulls their own score up, and there is no running tally to drift.

**The human gate is real.** `--approve` sets `status = 'APPROVED'` with a name
and timestamp in our own database and does nothing else. There is no code path
in this project that contacts a supplier, and the schema is shaped so a
recommendation cannot quietly become an order.

## The full chain — one command

```bash
python scripts/demo.py                          # scenario one: a disruption arrives
python scripts/demo.py --scenario bom           # scenario two: a new board arrives
python scripts/demo.py --scenario both --pause  # both, in order -- the full story
python scripts/demo.py --offline                # no network at all
python scripts/demo.py --approve "Your Name"    # include the human gate
```

Two scenarios, one engine:

| scenario | acts | the story |
|---|---|---|
| `news` | 6 | export restriction → 5,130 short → substitute → $56,960 plan → human |
| `bom` | 5 | spreadsheet → monitored product → build gap → *the same* substitute and sourcing |

`--scenario both` is the strongest run: the disruption happens, then the new
board lands into it. Scenario two's sourcing step reports *"2 supplier(s) are
still flagged by the live disruption, so they are excluded here too"* — the new
entry point inherits what the news monitor already found, rather than
rediscovering it or ignoring it.

`demo.py` resets the platform tables first, so it tells the same story every
run. Six acts: the position this morning (everything balanced, nothing flagged),
the notice arriving, the shortage, the substitute, the sourcing plan, the
signature. `--pause` waits on Enter between them.

The agents can also be run one at a time:

```bash
python scripts/run_intelligence.py --groq --reset --only EVT-2026-09-02-001
python scripts/run_supply_risk.py --ledger
python scripts/run_component.py --checks
python scripts/run_procurement.py
```

```
news notice, never seen before
  → [1] STM32F407VGT6 at risk: 4,000 units on PO-2026-0187, ~42 day delay
  → [3] short 4,000 from 2026-10-22  [CRITICAL]   (0 without the disruption)
  → [4] STM32F429VGT6 verified against MC-3000 and SD-220, 21 checks
  → [5] 2,400 Mouser + 1,600 Avnet, $43,720, all in by 2026-09-18
  → human approves
```

## Stage 2 — the Demand Forecasting Agent

`agents/demand/` — answers *"how much will we need?"*. **Supporting agent, not
the headline**: every ERP and SCM suite already does this well. It is here
because the shortage calculation needs a demand number.

```bash
python scripts/run_demand.py              # 2 months, matching the risk horizon
python scripts/run_demand.py --months 6   # past where the order book reaches
python scripts/run_demand.py --history    # print the fitted series
```

Holt-Winters exponential smoothing (statsmodels), additive trend plus a yearly
seasonal term, called **as a tool**. No language model touches these numbers —
asking one to extrapolate a time series is the shortest path to a hallucinated
quantity on a purchase order.

Reconciliation uses the standard MRP rule, **forecast consumption**: per month,
demand is the *greater* of the committed order book and the forecast. Adding
them would double-count every order a customer has already placed.

```
STM32F407VGT6      committed   forecast        net
  Sep 2026             3,551      5,015      5,015    forecast leads
  Oct 2026             6,070      5,052      6,070    order book leads
  total                9,621     10,067     11,085
```

Two caveats the code states rather than hides:

- 24 months is exactly two seasonal cycles — the documented **minimum** for
  fitting a yearly term. It fits; it is thinly evidenced, and every forecast
  prints that note.
- In-sample RMSE is 11–50 units, which is implausibly good. The history is
  synthetic and generated with a small noise term, so the model is fitting data
  built to be fittable. Real demand is far noisier and these intervals would be
  much wider.

**Wired into agent 3, on an aligned window.** The forecast is monthly, the risk
horizon is a rolling 60 days, so each month is prorated by how many of its days
fall inside the window — 3 Sep–2 Nov takes 28/30 of September, all of October,
2/30 of November. With that alignment the committed totals agree exactly
(10,000 either side), which they did not before.

Only the **uncovered** part of the forecast reaches agent 3 — net minus
committed. The committed orders are already in its ledger as real dated
movements, so passing the whole forecast would count them twice. Uncovered
demand is dated at the midpoint of each month's slice: month start would
overstate urgency, month end would understate it.

What it changes:

```
                        book only    + forecast
demand                     10,000        11,130
yesterday, short                0         1,130
today, short                4,000         5,130
first short on         2026-10-22    2026-10-15
```

The forecast says the company was already 1,130 light before any news arrived —
demand nobody has ordered yet. `demo.py` shows the signed order book alone in
act 0 and introduces the forecast in act 2, labelled, because "we are short"
means something different coming from a model than from a customer PO.

## Second entry point — a BOM document

`agents/bom_intake/` — a board arrives as a spreadsheet instead of a news story.
Same engine downstream.

```bash
python scripts/run_bom_intake.py samples/sensor_hub_SH-100.csv \
    --sku SH-100 --name "Sensor Hub SH-100" --qty 500 --need-by 2026-11-15
python scripts/run_build_check.py --ledger
python scripts/run_component.py        # unchanged
python scripts/run_procurement.py      # unchanged
python scripts/run_suggest.py --llm    # what about the parts that did not match?
```

The parser is vendored from **CircuitMind** (Shruthi-Joshi), `docai/parser.py` —
genuinely standalone, so it was worth taking rather than rewriting. Three bugs
were fixed on the way in; the file header lists them. The worst: its MPN regex
required a hyphen, so every part like `STM32F407VGT6` was invisible to it in
free text, PDF and OCR.

**Registration is permanent.** A parsed BOM becomes a row in `erp.products` with
real `erp.bom` lines, so the board is watched from that moment — the news monitor
traced the China export restriction to `SH-100` immediately, with no code change:

```
[HIGH] STM32F407VGT6  boards: MC-3000, SD-220, SH-100
```

**The build check is incremental, not isolated.** "Do we have 500 chips?" is the
flattering question and the wrong one — that stock is already promised to other
customers. The real question is whether we can build this *on top of* the
committed order book, and the baseline separates the two cases:

```
STM32F407VGT6  short 1,630  [HIGH]
  without this build you would be short 1,130 -- this build adds 500 of it
```

**Matching is narrow on purpose.** `EXACT`, `NORMALISED` (case, whitespace,
distributor suffixes like `-ND` and `-TR`), or `UNKNOWN`. No fuzzy matching:
`STM32F407VGT6` and `STM32F407VET6` differ by one character and by 512 KB of
flash. An unmatched line costs a minute; a wrongly matched one ships.

**Derived design constraints are deliberately weak.** A BOM document carries part
numbers, not footprints and rail voltages — those live in CAD and PLM. Intake
derives only `footprint_id` and `pinout_family`, read straight off the fitted
part. It does not guess a voltage or a temperature grade, because a 5 V board and
a 3.3 V board can fit the same chip. So agent 4 checks that a substitute for
`SH-100` physically mounts, and nothing more — against eleven checks for
`MC-3000`. Real deployments read the full set from PLM.

### Unmatched parts

`run_suggest.py` ranks the catalogue for an unmatched part and, with `--llm`,
asks what the part actually is. The two methods disagree usefully on `LM358DR`:

| method | answer |
|---|---|
| text similarity | three CAN transceivers, top score 0.23 — they share "SOIC-8" and nothing else |
| model, with the category enum | `NONE` at 0.99 — "we stock no part of this class at all" |

The similarity code is CircuitMind's hash-embedding fallback, vendored: their
primary path is `all-MiniLM-L6-v2` + pgvector, which this machine cannot run
(torch is ~2 GB against ~400 MB free, and pgvector is not installed). Over a
30-part catalogue it is a list comprehension anyway. Neither path resolves
anything automatically — both produce a shortlist for a person.

## Still open

- **Ingestion** is not built. Events are seeded rows; a real deployment polls a
  feed and inserts with `status = 'NEW'`, which is the only seam it needs.
- **Days-of-cover is not computed for origin exposure.** A `PART_ORIGIN` hit
  correctly says "replenishment at risk" but does not yet answer the obvious
  next question: *how many weeks of stock do we have before that matters?* The
  ledger in agent 3 could answer it; it is not wired to.
