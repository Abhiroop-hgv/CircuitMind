"""
Can we build it? Runs the buildability check on a registered build request.

    python scripts/run_build_check.py                # latest request
    python scripts/run_build_check.py --request 1
    python scripts/run_build_check.py --ledger       # show the working

Writes platform.shortages, so scripts/run_component.py and
scripts/run_procurement.py then run on the result unchanged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.bom_intake.buildability import BuildabilityAgent  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78


def latest_request(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM platform.build_requests ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", type=int, default=None)
    ap.add_argument("--ledger", action="store_true", help="print the stock ledger")
    args = ap.parse_args()

    with connect() as conn:
        request_id = args.request or latest_request(conn)
        if request_id is None:
            print("no build requests. Run scripts/run_bom_intake.py first.")
            return 1

        agent = BuildabilityAgent(conn)
        a = agent.assess(request_id)
        written = agent.persist(a)

        print(RULE)
        print(f"{a.name} ({a.sku}) -- build {a.build_qty:,} by {a.need_by}")
        print(RULE)
        print(f"  {len(a.lines)} components on the BOM, checked on top of everything")
        print(f"  already committed to existing customers.\n")

        print(f"  {'part':<24}{'per board':>10}{'needed':>10}{'stock':>9}{'short':>9}")
        for line in sorted(a.lines, key=lambda l: -l.shortage.shortage_qty):
            s = line.shortage
            short = f"{s.shortage_qty:,}" if s.shortage_qty else "-"
            print(f"  {line.mpn:<24}{line.qty_per_board:>10,}{line.required:>10,}"
                  f"{s.usable_stock:>9,}{short:>9}")

        print()
        if a.unknown_mpns:
            print(f"  {len(a.unknown_mpns)} part(s) never matched the catalogue and are not")
            print(f"  in this check at all: {', '.join(a.unknown_mpns)}")
            print("  The build cannot honestly be called feasible until they are resolved.\n")

        blocked = a.blocked_by
        if not blocked:
            print("  Nothing is short. Every part is covered even after the existing")
            print("  order book is served first.")
        else:
            print(f"  {len(blocked)} component(s) short:\n")
            for line in blocked:
                s = line.shortage
                cause = ("pre-existing -- short before this build was added"
                         if s.baseline_shortage_qty >= s.shortage_qty
                         else f"this build adds {s.shortage_qty - s.baseline_shortage_qty:,} of it")
                print(f"    {line.mpn}  short {s.shortage_qty:,}  [{s.severity}]")
                print(f"      needed {line.required:,} for the build, "
                      f"{s.usable_stock:,} usable in stock")
                print(f"      first short on {s.first_shortfall_date}")
                print(f"      without this build you would be short "
                      f"{s.baseline_shortage_qty:,} -- {cause}")
                print()

            if args.ledger:
                for line in blocked:
                    print(f"    ledger for {line.mpn}")
                    for row in line.shortage.ledger:
                        print(f"      {row['date']:<12}{row['kind']:<16}{row['ref'][:16]:<18}"
                              f"{row['qty']:>9,}{row['balance']:>10,}")
                    print()

        print(RULE)
        if written:
            print(f"  {written} shortage row(s) written. Now run, unchanged:")
            print("    python scripts/run_component.py     -- find substitutes")
            print("    python scripts/run_procurement.py   -- price the buy")
        else:
            print("  nothing handed on -- no shortages to solve.")
        print(RULE)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
