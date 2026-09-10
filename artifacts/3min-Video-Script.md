# CircuitMind — 3-Minute Video Script

**Team Satyatma** · Yukti Manthan 2.0
Members: Abhiroop, Vishnu, Aravind, SreePhaneesh, Shruthi · Mentors: Pushkar, Vishal

Pace target ≈ 150 words/min. Word counts per block are sized to the time slot —
if you speak faster, add a beat of silence rather than more words.

---

## 0:00–0:10 · Opening — name, logo, one-line promise

**ON SCREEN:** CircuitMind logo, full screen. Tagline fades in: *"From disruption to decisions."*

**ABHIROOP (VO):**
> This is CircuitMind. When the outside world disrupts your supply chain, it
> tells you what it did to *your* part numbers — and hands you a costed plan to
> fix it.

*(~28 words)*

---

## 0:10–0:20 · Team + mentors

**ON SCREEN:** Team photo, five names captioned. Then mentors' names/photos.

**SHRUTHI (VO):**
> We're Team Satyatma — Abhiroop, Vishnu, Aravind, SreePhaneesh and Shruthi.
> Mentored by Pushkar and Vishal.

*(~18 words — leave 2s of breathing room on the photos)*

---

## 0:20–0:35 · The Problem

**ON SCREEN:** Two large statements, one at a time. Minimal words.
1. *"A trade notice breaks. Which of your parts does it touch?"*
2. *"Nobody knows for days."*

**VISHNU (VO):**
> An export control, a port closure, a fab fire. Your ERP records what you hold —
> it can't read the news. So a planner spends days cross-referencing notices
> against bills of materials by hand, and the answer arrives too late to act on.

*(~42 words)*

---

## 0:35–0:50 · Our Solution

**ON SCREEN:** One line: *"Reads the event → resolves it against your data → costed plan for a human to approve."*

**ARAVIND (VO):**
> CircuitMind sits on top of the ERP you already run. It reads an event that has
> already happened, resolves it against your BOM, inventory and supplier lanes,
> verifies substitute parts by rule, and produces a multi-supplier purchase plan.
> It's built for procurement teams at semiconductor and PCBA manufacturers.

*(~46 words)*

---

## 0:50–2:20 · ⭐ Product Demo (live, working product)

**ON SCREEN:** Screen recording of the running app. No slides.

**SREEPHANEESH (VO), walking the screen:**

> Here's a real notice in the feed: an export licence requirement on
> microcontroller shipments out of China. One click to analyse.
>
> CircuitMind matches it to **STM32F407VGT6** by supplier lane — it's on our
> MC-3000 and SD-220 boards. The stock ledger runs our committed orders and a
> demand forecast against usable inventory and dates every movement. Result:
> **5,130 units short by the 15th of October**.
>
> Now substitutes. Candidates are retrieved by category, then checked against
> each board's design constraints, rule by rule. **STM32F429VGT6 passes** on both
> boards. Two close cousins are **rejected on footprint** — STM32F429ZIT6 is
> LQFP-144, STM32F405RGT6 is LQFP-64, and both boards need LQFP-100. A similarity
> score would have waved them through; the rule engine doesn't.
>
> Procurement excludes the suppliers hit by the event, ranks the rest on price
> adjusted for their on-time record, and splits the buy three ways: **3,000 from
> Avnet, 2,000 from DigiKey, 130 from Mouser**.
>
> The plan: **5,130 units, $56,960.50, landing 23 days early**. Status —
> *pending approval*. Nothing is ordered. It waits for a named person to sign.
>
> And every number on this screen — every quantity, price and date — traces back
> to a database query. The model chose which questions to ask. The database
> answered them.

*(~215 words — this is the heart of the video; rehearse to hit 1:30 exactly)*

---

## 2:20–2:40 · Key Features / AI / Technology

**ON SCREEN:** 4 quick cards.

**SHRUTHI (VO):**
> Four things make it trustworthy. **One** — constrained decoding: the model can
> only emit categories that exist in your data. **Two** — compatibility is decided
> by a deterministic rule engine, never a similarity guess. **Three** — a running
> stock ledger with Holt-Winters demand, every movement dated. **Four** — a
> read-only database role, so it physically cannot write to your system of record.

*(~55 words)*

---

## 2:40–2:52 · Impact / Who benefits / Why it matters

**ON SCREEN:** *"Days of manual cross-referencing → a defensible plan in minutes."*

**VISHNU (VO):**
> For a procurement lead, this turns days of manual work into minutes — and turns
> a panicked reaction into a plan you can defend in the room, with the rejected
> options and the reason for each shown alongside.

*(~38 words)*

---

## 2:52–3:00 · Close

**ON SCREEN:** CircuitMind logo + "Team Satyatma" + *"Built at Yukti Manthan 2.0"*.

**ABHIROOP (VO):**
> CircuitMind. From disruption to decisions. Built at Yukti Manthan 2.0 by
> Team Satyatma. Thank you.

*(~18 words)*

---

### Speaker map (5 voices, roughly even)

| Speaker | Blocks |
|---|---|
| Abhiroop | Opening, Close |
| Shruthi | Team intro, Key Features |
| Vishnu | Problem, Impact |
| Aravind | Solution |
| SreePhaneesh | Demo |

### Demo numbers (verify against the live app before recording)

- Short **5,130** units by **15 October** *(check the live app — the dashboard "watch" widget currently shows gap 0; the shortage figure is on recommendation #1)*
- Substitute **STM32F429VGT6** verified (PASS on MC-3000 and SD-220)
- Rejected on footprint: **STM32F429ZIT6** (LQFP-144), **STM32F405RGT6** (LQFP-64) vs required **LQFP-100**
- Split: Avnet **3,000 @ $11.05** (arr 15 Sep), DigiKey **2,000 @ $11.20** (arr 10 Sep), Mouser **130 @ $10.85** (arr 22 Sep)
- Total **$56,960.50**, latest arrival **22 September** vs need-by 15 October, status **PENDING_APPROVAL**
