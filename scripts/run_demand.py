"""
Run the Demand Forecasting Agent.

    python scripts/run_demand.py             # 60 days, the same window agent 3 uses
    python scripts/run_demand.py --days 180  # past where the order book reaches
    python scripts/run_demand.py --history   # print the fitted series

Statistical model called as a tool. No language model anywhere in this agent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.demand.agent import DemandAgent  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78
WATCH = "STM32F407VGT6"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60, help="horizon in days")
    ap.add_argument("--history", action="store_true", help="print the fitted series")
    args = ap.parse_args()

    with connect() as conn:
        agent = DemandAgent(conn, horizon_days=args.days)

        print(RULE)
        print(f"horizon {agent.today} .. {agent.horizon_end}   "
              f"({args.days} days, the same window the Supply Risk Agent uses)")
        print(RULE)
        print("  month slices:")
        for seg in agent.segments:
            print(f"    {seg.month.strftime('%b %Y')}  {seg.start} to {seg.end}   "
                  f"{seg.days_in_window} of {seg.days_in_month} days "
                  f"({seg.share * 100:.0f}% of the month)")

        print()
        print(RULE)
        print("product forecasts")
        print(RULE)
        product_forecasts = agent.forecast_products()
        for pf in product_forecasts:
            r = pf.result
            print(f"\n  {pf.sku}   {r.method}")
            print(f"    fitted on {r.history_points} months, in-sample RMSE {r.fitted_rmse:,.0f}")
            if args.history:
                print(f"    history: {', '.join(f'{h:,}' for h in pf.history)}")
            for i, seg in enumerate(agent.segments):
                print(f"    {seg.month.strftime('%b %Y')}  full month {r.points[i]:>7,}"
                      f"   (80% range {r.lower[i]:,} to {r.upper[i]:,})")
        if product_forecasts and product_forecasts[0].result.caveat:
            print(f"\n  note: {product_forecasts[0].result.caveat}")

        print()
        print(RULE)
        print("component demand, prorated into the window and reconciled")
        print(RULE)
        print("  net = MAX(committed order book, forecast) per month slice.")
        print("  Adding them would double-count every order already placed.\n")

        demands = agent.explode(product_forecasts)
        agent.persist(demands, product_forecasts)

        print(f"  {'component':<24}{'committed':>12}{'forecast':>12}{'net':>12}")
        for d in demands[:10]:
            print(f"  {d.mpn:<24}{d.total_committed:>12,}"
                  f"{sum(d.forecast):>12,}{d.total_net:>12,}")

        watch = next((d for d in demands if d.mpn == WATCH), None)
        if watch:
            print()
            print(RULE)
            print(f"  {WATCH} in detail")
            print(RULE)
            print(f"    {'slice':<22}{'committed':>12}{'forecast':>12}{'net':>12}{'uncovered':>12}")
            for i, seg in enumerate(watch.segments):
                label = f"{seg.month.strftime('%b')} ({seg.days_in_window}d)"
                print(f"    {label:<22}{watch.committed[i]:>12,}{watch.forecast[i]:>12,}"
                      f"{watch.net[i]:>12,}{watch.uncovered[i]:>12,}")
            print(f"    {'-' * 70}")
            print(f"    {'total':<22}{watch.total_committed:>12,}{sum(watch.forecast):>12,}"
                  f"{watch.total_net:>12,}{sum(watch.uncovered):>12,}")
            print()
            print(f"    driven by: {', '.join(f'{k} x{v:,}' for k, v in watch.drivers.items())}")
            print()
            uncovered = sum(watch.uncovered)
            if uncovered == 0:
                print("    The forecast sits at or below the signed order book across every")
                print("    slice, so the book governs and agent 3 is unaffected.")
            else:
                print(f"    {uncovered:,} units of demand nobody has ordered yet. Agent 3 adds")
                print( "    only this uncovered part -- the committed orders are already in")
                print( "    its ledger as real dated movements, and counting them twice")
                print( "    would inflate the shortage.")
        print(RULE)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
