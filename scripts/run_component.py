"""
Run the Component Intelligence Agent over whatever the Supply Risk Agent found.

    python scripts/run_component.py             # verdicts
    python scripts/run_component.py --checks    # every check, required vs actual

No model. Retrieval is a category filter; the decisions are rules.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.component.agent import ComponentAgent, handoff_to_procurement  # noqa: E402
from agents.component.rules import failures  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78


def shortages(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT s.event_id, s.component_id, c.mpn, s.shortage_qty,
                      s.first_shortfall_date, s.severity,
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
    ap.add_argument("--checks", action="store_true", help="show every check, not just failures")
    args = ap.parse_args()

    with connect() as conn:
        agent = ComponentAgent(conn)
        jobs = shortages(conn)

        if not jobs:
            print("no shortages recorded. Run scripts/run_supply_risk.py first.")
            return 0

        for job in jobs:
            print(RULE)
            print(f"replace {job['mpn']} -- {job['shortage_qty']:,} units "
                  f"needed by {job['first_shortfall_date']} [{job['severity']}]")
            print(RULE)

            candidates = agent.assess(job["component_id"], list(job["affected"] or []))
            agent.persist(job["event_id"], job["component_id"], candidates)

            boards = [b.sku for b in candidates[0].boards] if candidates else []
            print(f"  must satisfy every board that fits it: {', '.join(boards) or 'none'}")
            print(f"  {len(candidates)} candidate(s) retrieved, verified against "
                  f"{len(boards)} design spec(s)\n")

            for c in candidates:
                mark = "PASS" if c.verdict == "PASS" else "FAIL"
                print(f"  [{mark}] {c.mpn:<20} {c.manufacturer[:22]:<24} "
                      f"${c.standard_cost:>7.2f}  fit {c.score}%")

                if c.verdict == "PASS":
                    print(f"         origin {c.country_of_origin} -- {c.sourcing_note}")
                else:
                    bad = c.first_failure
                    if bad:
                        print(f"         rejected: {bad.name} -- needs {bad.required}, "
                              f"has {bad.actual}")

                if args.checks:
                    for b in c.boards:
                        print(f"         {b.sku} [{b.verdict}]")
                        for chk in b.checks:
                            print(f"           {'ok  ' if chk.ok else 'FAIL'} {chk.name:<22}"
                                  f" need {chk.required:<26} has {chk.actual}")
                elif c.verdict == "FAIL":
                    # one line per distinct reason, not once per board
                    seen, rest = {bad.name if bad else None}, []
                    for b in c.boards:
                        for f in failures(b.checks):
                            if f.name not in seen:
                                seen.add(f.name)
                                rest.append(f.name)
                    if rest:
                        print(f"         also fails: {', '.join(rest)}")
                print()

            passing = handoff_to_procurement(conn, job["component_id"])
            print(RULE)
            if not passing:
                print("  no verified alternative. This one goes to an engineer, not a buyer.")
            else:
                print("  handoff to Procurement Agent -- approved to buy:")
                for p in passing:
                    print(f"    {p['mpn']:<20} fit {p['compatibility_score']}%  {p['sourcing_note']}")
            print(RULE)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
