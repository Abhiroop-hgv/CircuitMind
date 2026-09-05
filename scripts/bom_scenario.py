"""
Second demo scenario: a new board arrives as a spreadsheet.

Four acts rather than six. The point of this one is not that it does something
new -- it is that the SAME engine picks it up. A document comes in one door, a
news story comes in the other, and everything downstream is shared.
"""

from __future__ import annotations

from datetime import date

from _theatre import WATCH_MPN, WIDTH, act, beat, wrap

from agents.bom_intake.buildability import BuildabilityAgent
from agents.bom_intake.intake import ingest
from agents.bom_intake.resolve import EXACT, NORMALISED, UNKNOWN
from agents.bom_intake.similarity import rank
from agents.component.agent import ComponentAgent, handoff_to_procurement
from agents.procurement.agent import ProcurementAgent, approve
from agents.procurement.reliability import compute as compute_scores
from agents.procurement.reliability import persist as persist_scores

SKU = "SH-100"
NAME = "Sensor Hub SH-100"
BUILD_QTY = 500
NEED_BY = date(2026, 11, 15)


def run(conn, args) -> None:
    _reset(conn)

    # ------------------------------------------------------------------ 1
    act(1, "A new board arrives", "as a spreadsheet, from engineering")
    intake = ingest(conn, args.bom, sku=SKU, name=NAME,
                    build_qty=BUILD_QTY, need_by=NEED_BY)
    counts = intake.counts

    print(f"  {intake.filename}  ->  build {BUILD_QTY:,} by {NEED_BY}")
    print(f"  {counts['total']} lines parsed: {counts[EXACT]} matched exactly, "
          f"{counts[NORMALISED]} after normalising, {counts[UNKNOWN]} unmatched")
    print()
    for line in intake.lines[:4]:
        print(f"    {line.reference_designator:<5}{line.mpn_raw:<24}"
              f"x{line.quantity_per_board:<5}{line.resolution}")
    print("    ...")
    for line in intake.unknown:
        print(f"    {line.reference_designator:<5}{line.mpn_raw:<24}"
              f"x{line.quantity_per_board:<5}NOT IN THE CATALOGUE")
    beat(args.pause)

    # ------------------------------------------------------------------ 2
    act(2, "It becomes a real product", "not a quote -- it is watched from now on")
    print(f"  registered as erp.products id={intake.product_id}, "
          f"{len(intake.resolved)} BOM lines")
    print()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.sku FROM erp.bom b
                 JOIN erp.products p   ON p.id = b.product_id
                 JOIN erp.components c ON c.id = b.component_id
                WHERE c.mpn = %s ORDER BY p.sku""",
            (WATCH_MPN,),
        )
        boards = [r[0] for r in cur.fetchall()]
    print(f"  {WATCH_MPN} is now fitted on: {', '.join(boards)}")
    print("  The news monitor, the forecaster and the shortage calculation all see")
    print("  this board from here on. No code changed to make that true.")
    beat(args.pause)

    # ------------------------------------------------------------------ 3
    act(3, f"Can we build {BUILD_QTY} of them?", "on top of what is already promised")
    build = BuildabilityAgent(conn)
    assessment = build.assess(intake.request_id)
    written = build.persist(assessment)

    print(f"  {len(assessment.lines)} components checked out to {NEED_BY}")
    print()
    ranked = sorted(assessment.lines, key=lambda l: -l.shortage.shortage_qty)
    for line in ranked[:3]:
        s = line.shortage
        state = f"short {s.shortage_qty:,}" if s.shortage_qty else "covered"
        print(f"    {line.mpn:<24}need {line.required:>7,}   "
              f"stock {s.usable_stock:>8,}   {state}")
    print(f"    ... the other {len(assessment.lines) - 3} are covered")
    print()

    for line in assessment.blocked_by:
        s = line.shortage
        added = s.shortage_qty - s.baseline_shortage_qty
        print(f"  {line.mpn}: short {s.shortage_qty:,} [{s.severity}], "
              f"first short {s.first_shortfall_date}")
        print(f"    You would be short {s.baseline_shortage_qty:,} without this board.")
        print(f"    Building it adds {added:,} more.")

    if assessment.unknown_mpns:
        print()
        print(f"  {', '.join(assessment.unknown_mpns)} never matched the catalogue, so it")
        print("  is not in this check at all. The build is not feasible until someone")
        print("  resolves it -- the system will not pretend otherwise.")
    beat(args.pause)

    # ------------------------------------------------------------------ 4
    act(4, "The same engine takes over", "substitution and sourcing, unchanged")
    if not written:
        print("  nothing short -- no work for agents 4 and 5.")
    else:
        _shared_tail(conn, args)
    beat(args.pause)

    # ------------------------------------------------------------------ 5
    act(5, "The part nobody recognised", "a shortlist, never an answer")
    parts = _catalogue(conn)
    for line in intake.unknown:
        print(f"  {line.mpn_raw} -- \"{line.description}\"")
        print("  closest by text similarity:")
        for row, score in rank(f"{line.mpn_raw} {line.description}", parts, top_k=3):
            print(f"    {score:>6.3f}  {row['mpn']:<22}{row['category']}")
        print()
        print("  Every one of those is a CAN transceiver. They share the words")
        print("  \"SOIC-8\" and \"dual\" with an op-amp and nothing else at all.")
        print("  Text overlap is not understanding, which is why nothing here is")
        print("  resolved automatically. Asked properly, the model answers NONE:")
        print("  we stock no part of this class, so it has to be added and sourced")
        print("  on its own merits.   (scripts/run_suggest.py --llm)")

    print()
    print("━" * WIDTH)
    print("  a spreadsheet → a monitored product → a build gap → the same engine")
    print("━" * WIDTH)


# ---------------------------------------------------------------------------

def _reset(conn) -> None:
    """A demo has to give the same answer every time it runs."""
    with conn.cursor() as cur:
        cur.execute(
            """DELETE FROM platform.shortages WHERE build_request_id IN
                 (SELECT id FROM platform.build_requests WHERE product_sku = %s)""",
            (SKU,),
        )
        cur.execute("DELETE FROM platform.build_requests WHERE product_sku = %s", (SKU,))
    conn.commit()


def _catalogue(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, mpn, manufacturer, category, description, specs
                 FROM erp.components WHERE lifecycle = 'ACTIVE'"""
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _live_disruptions(conn):
    """Suppliers any current event has flagged. A new board does not get to
    forget what the news monitor already found."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COALESCE(array_agg(DISTINCT x), '{}')
                 FROM platform.event_impacts ei
                 CROSS JOIN LATERAL unnest(ei.affected_supplier_ids) AS x
                WHERE ei.risk_level IN ('HIGH', 'MEDIUM')"""
        )
        return list(cur.fetchone()[0] or [])


def _shared_tail(conn, args) -> None:
    """Agents 4 and 5, driven from whatever is sitting in platform.shortages."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT s.component_id, c.mpn, s.shortage_qty, s.first_shortfall_date
                 FROM platform.shortages s
                 JOIN erp.components c ON c.id = s.component_id
                WHERE s.shortage_qty > 0 AND s.build_request_id IS NOT NULL
                ORDER BY s.shortage_qty DESC LIMIT 1"""
        )
        row = cur.fetchone()
    if not row:
        print("  nothing short.")
        return

    component_id, mpn, qty, need_by = row
    affected = _live_disruptions(conn)
    if affected:
        print(f"  {len(affected)} supplier(s) are still flagged by the live disruption,")
        print("  so they are excluded here too.")
        print()

    comp = ComponentAgent(conn)
    candidates = comp.assess(component_id, affected)
    comp.persist(None, component_id, candidates)
    for c in [x for x in candidates if x.verdict == "PASS"][:2]:
        print(f"    [PASS] {c.mpn:<16} ${c.standard_cost:>6.2f}   {c.sourcing_note}")
    print()

    persist_scores(conn, compute_scores(conn))
    proc = ProcurementAgent(conn)
    result = proc.recommend(component_id=component_id, mpn=mpn, qty=qty, need_by=need_by,
                            alternatives=handoff_to_procurement(conn, component_id),
                            affected_suppliers=affected)
    reco_id = proc.persist(None, component_id, qty, need_by, result)
    plan = result["plan"]

    print(f"  recommended: {plan.name}")
    for l in plan.lines:
        print(f"    {l.supplier[:24]:<26}{l.quantity:>6,} x {l.mpn:<14}"
              f"${l.total:>10,.2f}   {l.arrival}  score {l.score:.2f}")
    print(f"    {'total':<26}{'':>6}   {'':<15}${plan.total_cost:>10,.2f}")
    print()
    for line in wrap(result["rationale"], WIDTH - 6):
        print(f"  {line}")
    print()
    if args.approve:
        approve(conn, reco_id, args.approve)
        print(f"  recommendation #{reco_id} APPROVED by {args.approve}. Nothing ordered.")
    else:
        print(f"  recommendation #{reco_id} PENDING_APPROVAL.")
