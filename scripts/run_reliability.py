"""
Score every supplier on whether they actually deliver when they say they will.

    python scripts/run_reliability.py            # compute and store
    python scripts/run_reliability.py --history  # show recent deliveries

Reads closed purchase orders: promised date against the date the goods turned
up. No model. A buyer can reproduce every figure in a spreadsheet, which matters
when you have to tell a supplier why they lost an order.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.procurement.reliability import compute, persist  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", action="store_true", help="list recent deliveries")
    args = ap.parse_args()

    with connect() as conn:
        scores = compute(conn)
        persist(conn, scores)

        print(RULE)
        print("supplier delivery performance, from closed purchase orders")
        print(RULE)
        print(f"  {'supplier':<28}{'score':>7}{'on time':>9}{'late':>6}"
              f"{'avg late':>10}{'worst':>7}{'padding':>9}")
        for s in sorted(scores, key=lambda x: -x.score):
            if s.unproven:
                print(f"  {s.name[:26]:<28}{s.score:>7.2f}{'-':>9}{'-':>6}"
                      f"{'-':>10}{'-':>7}{'-':>9}   too few deliveries")
                continue
            print(f"  {s.name[:26]:<28}{s.score:>7.2f}{s.on_time:>9}{s.late:>6}"
                  f"{s.avg_days_late:>9.1f}d{s.worst_days_late:>6}d"
                  f"{s.lead_time_padding:>8}d")

        print()
        print("  score    recency-weighted share of deliveries that hit the promised date")
        print("  padding  days added to this supplier's quoted lead time before we ask")
        print("           whether an order can arrive in time")

        if args.history:
            print()
            print(RULE)
            for s in sorted(scores, key=lambda x: x.score):
                if not s.history:
                    continue
                print(f"\n  {s.name}")
                for h in s.history[:6]:
                    late = h["days_late"]
                    tag = "on time" if late <= 0 else f"{late}d LATE"
                    print(f"    {h['po']:<16} promised {h['expected']}  "
                          f"arrived {h['actual']}   {tag}")
        print(RULE)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
