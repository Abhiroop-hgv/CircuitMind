"""
Run the Procurement Agent, and present the recommendation for approval.

    python scripts/run_procurement.py                      # build the recommendation
    python scripts/run_procurement.py --approve "A Sujay"  # the human gate

No order is ever placed. --approve records a decision in our own database and
does nothing else; there is no code in this project that contacts a supplier.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.component.agent import handoff_to_procurement  # noqa: E402
from agents.procurement.agent import ProcurementAgent, approve  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78


def jobs(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT s.event_id, s.component_id, c.mpn, s.shortage_qty,
                      s.first_shortfall_date,
                      COALESCE(i.affected_supplier_ids,
                          (SELECT COALESCE(array_agg(DISTINCT x), '{}')
                            FROM platform.event_impacts ei
                            CROSS JOIN LATERAL unnest(ei.affected_supplier_ids) AS x
                           WHERE ei.risk_level IN ('HIGH', 'MEDIUM'))) AS affected
                 FROM platform.shortages s
                 JOIN erp.components c ON c.id = s.component_id
                 LEFT JOIN platform.event_impacts i
                        ON i.event_id = s.event_id AND i.component_id = s.component_id
                WHERE s.shortage_qty > 0
                ORDER BY s.shortage_qty DESC"""
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approve", metavar="NAME",
                    help="approve the pending recommendation as this person")
    args = ap.parse_args()

    with connect() as conn:
        agent = ProcurementAgent(conn)
        work = jobs(conn)
        if not work:
            print("no shortages. Run scripts/run_supply_risk.py first.")
            return 0

        for job in work:
            alternatives = handoff_to_procurement(conn, job["component_id"])
            result = agent.recommend(
                component_id=job["component_id"],
                mpn=job["mpn"],
                qty=job["shortage_qty"],
                need_by=job["first_shortfall_date"],
                alternatives=alternatives,
                affected_suppliers=list(job["affected"] or []),
            )
            reco_id = agent.persist(job["event_id"], job["component_id"],
                                    job["shortage_qty"], job["first_shortfall_date"], result)
            _report(job, result, reco_id)

            if args.approve:
                if approve(conn, reco_id, args.approve):
                    print(f"  APPROVED by {args.approve}.")
                    print("  Recorded in our database. No order has been placed and no")
                    print("  supplier has been contacted -- this project has no code that can.")
                else:
                    print("  nothing pending to approve.")
                print()
    return 0


def _report(job, result, reco_id) -> None:
    plan = result["plan"]
    print(RULE)
    print(f"buy {job['shortage_qty']:,} x {job['mpn']} equivalent, "
          f"needed by {job['first_shortfall_date']}")
    print(RULE)

    print("  options costed:")
    for c in result["considered"]:
        verdict = "covers it" if c["viable"] else f"short {c['shortfall']:,}"
        cost = f"${c['total_cost']:>10,.2f}" if c["viable"] else " " * 11
        print(f"    {c['plan']:<44}{cost}  {verdict}")
    print()

    if not plan.viable:
        print("  NO VIABLE PLAN -- escalate to a buyer.")
        print(f"  {result['rationale']}")
        print(RULE)
        return

    print(f"  RECOMMENDATION #{reco_id}: {plan.name}")
    print(f"  {'-' * 72}")
    print(f"    {'supplier':<28}{'part':<16}{'qty':>7}{'unit':>9}{'total':>12}  arrives")
    for l in plan.lines:
        print(f"    {l.supplier[:26]:<28}{l.mpn:<16}{l.quantity:>7,}"
              f"{l.unit_price:>9.2f}{l.total:>12,.2f}  {l.arrival} "
              f"({l.lead_time_days}d)")
    print(f"  {'-' * 72}")
    print(f"    {'total':<51}{plan.total_cost:>12,.2f}  all in by {plan.latest_arrival}")
    print(f"    {'BOM change required':<51}{str(plan.requires_bom_change):>12}")
    print()
    print("  why:")
    for line in _wrap(result["rationale"], 70):
        print(f"    {line}")
    print()
    print(f"  status: PENDING_APPROVAL -- a person decides. Nothing has been ordered.")
    print(RULE)


def _wrap(text: str, width: int):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
