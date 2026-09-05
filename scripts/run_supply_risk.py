"""
Run the Supply Risk Agent over whatever the Intelligence Agent flagged.

    python scripts/run_supply_risk.py              # every open flag
    python scripts/run_supply_risk.py --ledger     # show the working, line by line

No model, no API key, no network. Just arithmetic against the database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.supply_risk.agent import SupplyRiskAgent, handoff_to_component_agent  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", action="store_true", help="print the full stock ledger")
    args = ap.parse_args()

    with connect() as conn:
        agent = SupplyRiskAgent(conn)
        flags = agent.handoffs()

        if not flags:
            print("nothing flagged by the Intelligence Agent. Run scripts/run_intelligence.py first.")
            return 0

        print(f"horizon: {agent.today} .. {agent.horizon_end}")
        print(f"{len(flags)} component(s) flagged\n")

        results = []
        for flag in flags:
            s = agent.assess(flag)
            agent.persist(flag["event_id"], s)
            results.append(s)
            _report(s, flag, args.ledger)

        print(RULE)
        rows = handoff_to_component_agent(conn)
        if not rows:
            print("no shortage. Nothing to hand to the Component Intelligence Agent.")
        else:
            print("handoff to Component Intelligence Agent:")
            for r in rows:
                print(f"  find an alternative for {r['mpn']} -- "
                      f"{r['shortage_qty']} units needed by {r['first_shortfall_date']} "
                      f"({r['severity']})")
        print(RULE)
    print()
    return 0


def _report(s, flag, show_ledger: bool) -> None:
    print(RULE)
    print(f"{s.mpn}   flagged {flag['risk_level']} by the Intelligence Agent")
    print(RULE)

    print(f"  committed demand                    {s.demand_qty:>8,}")
    print(f"  usable stock                        {s.usable_stock:>8,}")
    if s.incoming_on_time:
        print(f"  incoming, unaffected                {s.incoming_on_time:>8,}")
    if s.incoming_delayed:
        print(f"  incoming, delayed but still lands   {s.incoming_delayed:>8,}")
    if s.incoming_lost:
        print(f"  incoming, pushed past the horizon  -{s.incoming_lost:>8,}   not counted")
    print(f"  {'-' * 52}")
    print(f"  expected supply                     {s.expected_supply:>8,}")
    print()

    print(f"  without the disruption, short       {s.baseline_shortage_qty:>8,}"
          f"{'   <- nothing would have been flagged' if s.baseline_shortage_qty == 0 else ''}")
    if s.shortage_qty > 0:
        print(f"  WITH the disruption, short          {s.shortage_qty:>8,}   [{s.severity}]")
        print(f"  first short on                      {str(s.first_shortfall_date):>8}")
    else:
        print(f"  with the disruption, short          {s.shortage_qty:>8,}   [{s.severity}]")
    print()

    if show_ledger:
        first_negative = _first_negative_row(s)
        print("  stock ledger")
        print(f"    {'date':<12}{'movement':<18}{'ref':<16}{'qty':>8}{'balance':>10}")
        for row in s.ledger:
            mark = "  <-- runs out here" if row is first_negative else ""
            print(f"    {row['date']:<12}{row['kind']:<18}{row['ref'][:15]:<16}"
                  f"{row['qty']:>8,}{row['balance']:>10,}{mark}")
            if row["note"]:
                print(f"    {'':<12}{'':<18}{row['note'][:62]}")
        print()


def _first_negative_row(s):
    for row in s.ledger:
        if row["balance"] < 0:
            return row
    return None


if __name__ == "__main__":
    raise SystemExit(main())
