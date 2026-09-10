# -*- coding: utf-8 -*-
"""
Second demo scenario, from a BOM instead of a news event.

Reuses the real Sensor Hub SH-100 board already registered in the ERP (see
scripts/bom_scenario.py) and runs the same buildability, component and
procurement agents used there -- at a build quantity chosen so that the
unaffected suppliers cannot cover the MX25L12835FM2I-10G flash in full and
procurement swaps to the verified alternative W25Q128JVSIQ. Nothing here is
invented: every figure below is the live agents' output against the seeded
catalogue. The only thing this script chooses is the build quantity -- a
scenario parameter, the same way the original demo script hardcodes
BUILD_QTY = 500.

    python scripts/make_bom_split_po.py [--approve "Name"] [--build-qty N]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db.connection import connect
from agents.bom_intake.buildability import BuildabilityAgent
from agents.component.agent import ComponentAgent, handoff_to_procurement
from agents.procurement.agent import ProcurementAgent, approve
from agents.procurement.reliability import compute as compute_scores
from agents.procurement.reliability import persist as persist_scores

SKU = "SH-100"
FEATURED_MPN = "MX25L12835FM2I-10G"
NEED_BY = date(2026, 11, 15)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-qty", type=int, default=8500)
    ap.add_argument("--approve")
    args = ap.parse_args()

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM platform.build_requests
                 WHERE product_sku = %s ORDER BY id DESC LIMIT 1""", (SKU,))
        row = cur.fetchone()
        if not row:
            print(f"no build_request for {SKU} -- run scripts/bom_scenario.py first")
            return 1
        request_id = row[0]
        cur.execute(
            """UPDATE platform.build_requests SET build_qty = %s, need_by = %s
                WHERE id = %s""", (args.build_qty, NEED_BY, request_id))
        cur.execute("DELETE FROM platform.shortages WHERE build_request_id = %s",
                    (request_id,))
    conn.commit()

    print(f"ACT 1  {SKU} at build quantity {args.build_qty:,} (was 500)")
    build = BuildabilityAgent(conn)
    assessment = build.assess(request_id)
    build.persist(assessment)

    # Buildability raises a shortage for every blocked line on the board. This
    # scenario only demonstrates the flash, so drop the rest -- otherwise the
    # dashboard headline becomes an unrelated inductor and "active shortages"
    # jumps into the twenties.
    with conn.cursor() as cur:
        cur.execute(
            """DELETE FROM platform.shortages
                WHERE build_request_id = %s
                  AND component_id <> (SELECT id FROM erp.components WHERE mpn = %s)""",
            (request_id, FEATURED_MPN))
    conn.commit()

    featured = next((l for l in assessment.lines if l.mpn == FEATURED_MPN), None)
    if featured is None or featured.shortage.shortage_qty <= 0:
        print(f"  {FEATURED_MPN} is not short at this quantity -- raise --build-qty")
        return 1
    component_id, qty = featured.component_id, featured.shortage.shortage_qty
    print(f"  {FEATURED_MPN} short {qty:,}, first bites {featured.shortage.first_shortfall_date}")

    print(f"\nACT 2  substitute check -- same rule engine as the STM32 scenario")
    comp = ComponentAgent(conn)
    candidates = comp.assess(component_id, [])
    comp.persist(None, component_id, candidates)
    for c in candidates:
        print(f"    [{c.verdict:<4}] {c.mpn}")

    print(f"\nACT 3  procurement -- who actually holds this much stock")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT s.code, sc.stock_available FROM erp.supplier_components sc
                 JOIN erp.suppliers s ON s.id = sc.supplier_id
                WHERE sc.component_id = %s ORDER BY sc.stock_available DESC""",
            (component_id,))
        for code, stock in cur.fetchall():
            print(f"    {code}: {stock:,} in stock")

    persist_scores(conn, compute_scores(conn))
    proc = ProcurementAgent(conn)
    result = proc.recommend(
        component_id=component_id, mpn=FEATURED_MPN, qty=qty, need_by=NEED_BY,
        alternatives=handoff_to_procurement(conn, component_id),
        affected_suppliers=[])
    reco_id = proc.persist(None, component_id, qty, NEED_BY, result)
    plan = result["plan"]

    print(f"\n  recommendation #{reco_id}: {plan.name}  -- PENDING_APPROVAL")
    print(f"  {result['rationale']}")
    print()
    for l in plan.lines:
        print(f"    {l.supplier[:24]:<26}{l.quantity:>6,} x ${l.unit_price:<8}"
              f"${l.total:>10,.2f}   arrives {l.arrival}")
    print(f"    {'total':<26}{qty:>6,}              ${plan.total_cost:>10,.2f}")
    print(f"\n  {plan.suppliers} supplier line(s) -- "
          + ("a real split: no one distributor holds enough."
             if plan.suppliers > 1 else
             "single-sourced at this quantity -- raise --build-qty for a split."))

    if args.approve:
        approve(conn, reco_id, args.approve)
        conn.commit()
        print(f"\n  approved by {args.approve}")

    print(f"\nreco_id={reco_id}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
