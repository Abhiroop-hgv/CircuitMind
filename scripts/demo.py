"""
The whole chain, one command.

    python scripts/demo.py                       # live model, full run
    python scripts/demo.py --pause               # stop between acts to talk
    python scripts/demo.py --offline             # no network at all
    python scripts/demo.py --approve "A Sujay"   # include the human gate

Opens on the position as it stands this morning -- everything balanced, nothing
flagged -- then lets one news notice work through it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.component.agent import ComponentAgent, handoff_to_procurement  # noqa: E402
from agents.demand.agent import DemandAgent  # noqa: E402
from agents.intelligence.agent import IntelligenceAgent  # noqa: E402
from agents.intelligence.extract import FixtureExtractor  # noqa: E402
from agents.procurement.agent import ProcurementAgent, approve  # noqa: E402
from agents.procurement.reliability import compute as compute_scores  # noqa: E402
from agents.procurement.reliability import persist as persist_scores  # noqa: E402
from agents.supply_risk.agent import SupplyRiskAgent  # noqa: E402
from db.connection import connect  # noqa: E402
import bom_scenario  # noqa: E402

WIDTH = 78
DEFAULT_EVENT = "EVT-2026-09-02-001"
WATCH_MPN = "STM32F407VGT6"


def act(n: int, title: str, subtitle: str = "") -> None:
    print()
    print("━" * WIDTH)
    print(f"  ACT {n}   {title}")
    if subtitle:
        print(f"          {subtitle}")
    print("━" * WIDTH)
    print()


def beat(pause: bool) -> None:
    if pause:
        try:
            input("\n        [enter to continue]")
        except (EOFError, KeyboardInterrupt):
            pass
    else:
        time.sleep(0.4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="fixtures, no network")
    ap.add_argument("--pause", action="store_true", help="wait between acts")
    ap.add_argument("--approve", metavar="NAME", help="approve the recommendation as this person")
    ap.add_argument("--event", default=DEFAULT_EVENT)
    ap.add_argument("--model", default=None)
    ap.add_argument("--scenario", choices=("news", "bom", "both"), default="news",
                    help="news: a disruption arrives. bom: a new board arrives. "
                         "both: the disruption, then the board landing into it.")
    ap.add_argument("--bom", default="samples/sensor_hub_SH-100.csv")
    args = ap.parse_args()

    with connect() as conn:
        # everything back to the starting position, so the demo repeats exactly
        with conn.cursor() as cur:
            cur.execute("DELETE FROM platform.purchase_recommendations")
            cur.execute("DELETE FROM platform.alternatives")
            cur.execute("DELETE FROM platform.shortages")
            if args.scenario in ("news", "both"):
                cur.execute("DELETE FROM platform.event_impacts")
                cur.execute("UPDATE platform.external_events "
                            "SET status='NEW', extracted='{}'::jsonb")
            if args.scenario in ("bom", "both"):
                # The BOM scenario registers SH-100. Left over from a previous
                # run it would already be on the board list in scenario one,
                # which gives away the reveal. Wind it back.
                cur.execute("""DELETE FROM platform.shortages WHERE build_request_id IN
                                 (SELECT id FROM platform.build_requests
                                   WHERE product_sku = 'SH-100')""")
                cur.execute("DELETE FROM platform.build_requests WHERE product_sku = 'SH-100'")
                cur.execute("""DELETE FROM erp.bom WHERE product_id IN
                                 (SELECT id FROM erp.products WHERE sku = 'SH-100')""")
                cur.execute("DELETE FROM erp.products WHERE sku = 'SH-100'")
        conn.commit()

        if args.scenario in ("news", "both"):
            _news_scenario(conn, args)
        if args.scenario in ("bom", "both"):
            if args.scenario == "both":
                print()
                print("█" * WIDTH)
                print("  SCENARIO TWO -- later that week, a new board lands into all of that")
                print("█" * WIDTH)
            bom_scenario.run(conn, args)

    print()
    return 0


def _news_scenario(conn, args) -> None:
    """A disruption arrives from outside. The original six acts."""
    risk = SupplyRiskAgent(conn)

    # ---------------------------------------------------------------- 0
    act(0, "This morning", f"{WATCH_MPN} — the part every motor controller needs")
    _opening_position(conn, risk)
    beat(args.pause)

    # ---------------------------------------------------------------- 1
    if args.offline:
        extractor = FixtureExtractor()
    else:
        from agents.intelligence.groq_extract import DEFAULT_MODEL, GroqExtractor
        extractor = GroqExtractor(model=args.model or DEFAULT_MODEL)

    act(1, "A notice is published", f"read by {extractor.name}")

    agent = IntelligenceAgent(conn, extractor, explain=False)
    events = [e for e in agent.pending_events() if e["external_id"] == args.event]
    if not events:
        print(f"  no event {args.event}")
        return 1
    event = events[0]

    for line in _wrap(event["headline"], WIDTH - 6):
        print(f"  {line}")
    print()
    for line in _wrap(event["body"], WIDTH - 6):
        print(f"  {line}")
    print()

    started = time.time()
    outcome = agent.analyse(event)
    e = outcome.extraction
    print(f"  read in {time.time() - started:.1f}s — nothing about this company was shown to the model")
    print()
    print(f"    event type   {e.event_type}")
    print(f"    countries    {', '.join(e.countries) or '-'}")
    print(f"    categories   {', '.join(e.component_categories) or '-'}")
    print(f"    effective    {e.effective_date}")
    print(f"    delay        ~{e.expected_delay_days} days")
    print()
    print("  traced through the ERP:")
    for impact in sorted(outcome.impacts, key=lambda i: i["risk_level"]):
        m = impact["match"]
        print(f"    [{impact['risk_level']:<6}] {m.mpn:<16} {', '.join(m.product_skus) or 'not fitted'}"
              f"   {m.at_risk_qty:,} units in flight")
    beat(args.pause)

    # ---------------------------------------------------------------- 2
    act(2, "So do we run out?", "no model — arithmetic against the order book")

    # Demand first. Deliberately a preamble, not an act of its own: every
    # ERP already forecasts demand, and it is a supporting input here.
    demand_agent = DemandAgent(conn)
    product_forecasts = demand_agent.forecast_products()
    demands = demand_agent.explode(product_forecasts)
    demand_agent.persist(demands, product_forecasts)
    watch = next((d for d in demands if d.mpn == WATCH_MPN), None)
    if watch:
        print(f"  demand, same 60-day window ({product_forecasts[0].result.method}):")
        print(f"    {'signed order book':<38}{watch.total_committed:>9,}")
        print(f"    {'forecast on top, not yet ordered':<38}{sum(watch.uncovered):>9,}")
        print(f"    {'-' * 47}")
        print(f"    {'demand used':<38}{watch.total_net:>9,}")
        print()

    flags = risk.handoffs(outcome.event_id)
    shortage = None
    for flag in flags:
        s = risk.assess(flag)
        risk.persist(flag["event_id"], s)
        if s.mpn == WATCH_MPN:
            shortage = s
        print(f"  {s.mpn}")
        print(f"    {'demand (order book + forecast)':<38}{s.demand_qty:>9,}")
        print(f"    {'usable stock':<38}{s.usable_stock:>9,}")
        print(f"    {'the held shipment, no longer counted':<38}{-s.incoming_lost:>9,}")
        print(f"    {'-' * 47}")
        print(f"    {'yesterday, short':<38}{s.baseline_shortage_qty:>9,}")
        print(f"    {'today, short':<38}{s.shortage_qty:>9,}   [{s.severity}]")
        print(f"    {'first short on':<38}{str(s.first_shortfall_date):>9}")
    beat(args.pause)

    # ---------------------------------------------------------------- 3
    act(3, "What can go on the board instead?", "retrieval finds candidates, rules decide")
    comp = ComponentAgent(conn)
    job = {"component_id": shortage.component_id, "event_id": outcome.event_id}
    affected = [s for i in outcome.impacts if i["match"].mpn == WATCH_MPN
                for s in i["match"].supplier_ids]
    candidates = comp.assess(job["component_id"], affected)
    comp.persist(outcome.event_id, job["component_id"], candidates)

    boards = ", ".join(b.sku for b in candidates[0].boards)
    n_boards = len(candidates[0].boards) if candidates else 0
    print(f"  every candidate must satisfy all {n_boards} boards "
          f"that fit it: {boards}")
    print()
    for c in candidates:
        if c.verdict == "PASS":
            print(f"    [PASS] {c.mpn:<16} ${c.standard_cost:>6.2f}   {c.sourcing_note}")
        else:
            bad = c.first_failure
            print(f"    [FAIL] {c.mpn:<16} ${c.standard_cost:>6.2f}   "
                  f"{bad.name}: needs {bad.required}, has {bad.actual}")
    beat(args.pause)

    # ---------------------------------------------------------------- 4
    act(4, "Buy it from whom?", "cost, stock, lead time, and who actually delivers")

    # Score the suppliers on what they have actually done, before ranking
    # anything on price. Cheap and unreliable is not cheap.
    scores = compute_scores(conn)
    persist_scores(conn, scores)
    proven = sorted((s for s in scores if not s.unproven), key=lambda x: -x.score)
    print("  delivery record, from closed purchase orders:")
    for s in proven[:3] + proven[-2:]:
        print(f"    {s.name[:26]:<28}{s.score:>6.2f}   {s.on_time} on time, "
              f"{s.late} late" + (f", avg {s.avg_days_late:.0f}d over" if s.late else "")
              + (f"   (+{s.lead_time_padding}d added to their quote)"
                 if s.lead_time_padding else ""))
    print()

    proc = ProcurementAgent(conn)
    result = proc.recommend(
        component_id=shortage.component_id,
        mpn=shortage.mpn,
        qty=shortage.shortage_qty,
        need_by=shortage.first_shortfall_date,
        alternatives=handoff_to_procurement(conn, shortage.component_id),
        affected_suppliers=affected,
    )
    reco_id = proc.persist(outcome.event_id, shortage.component_id,
                           shortage.shortage_qty, shortage.first_shortfall_date, result)
    plan = result["plan"]

    for c in result["considered"]:
        state = (f"${c['total_cost']:>11,.2f}" if c["viable"]
                 else f"short {c['shortfall']:,}".rjust(12))
        print(f"    {c['plan']:<44}{state}")
    print()
    print(f"  recommended: {plan.name}")
    for l in plan.lines:
        print(f"    {l.supplier[:24]:<26}{l.quantity:>6,} x {l.mpn:<14}"
              f"${l.total:>10,.2f}   {l.arrival}  score {l.score:.2f}")
    print(f"    {'-' * 68}")
    print(f"    {'total':<26}{plan.shortfall + sum(x.quantity for x in plan.lines):>6,}"
          f"   {'':<15}${plan.total_cost:>10,.2f}   {plan.latest_arrival}")
    print()
    for line in _wrap(result["rationale"], WIDTH - 6):
        print(f"  {line}")
    beat(args.pause)

    # ---------------------------------------------------------------- 5
    act(5, "A person signs it", "nothing is ordered by the system, ever")
    if args.approve:
        approve(conn, reco_id, args.approve)
        print(f"  recommendation #{reco_id} APPROVED by {args.approve}")
        print("  written to our database. No supplier has been contacted —")
        print("  there is no code in this project that can.")
    else:
        print(f"  recommendation #{reco_id} is PENDING_APPROVAL.")
        print(f"  run again with --approve \"your name\" to close the loop.")

    print()
    print("━" * WIDTH)
    print(f"  one notice → {shortage.shortage_qty:,} unit gap → verified substitute "
          f"→ ${plan.total_cost:,.2f} plan → human")
    print("━" * WIDTH)


def _opening_position(conn, _risk) -> None:
    """
    The signed order book only -- no forecast, deliberately.

    Act 0 is the position a planner would see in the ERP this morning: real
    orders against real stock. The forecast enters in act 2 and is labelled as
    such, because "we are short" means something different when it comes from a
    model than when it comes from a customer purchase order.

    Using a committed-only agent here also stops the opening slide changing
    depending on whether a forecast happens to be sitting in the table.
    """
    committed_only = SupplyRiskAgent(conn, use_forecast=False)
    risk = committed_only

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM erp.components WHERE mpn = %s", (WATCH_MPN,))
        component_id = cur.fetchone()[0]

    demand = -sum(m.qty for m in risk.demand_movements(component_id))
    stock = risk.usable_stock(component_id)
    arrivals = risk.arrival_movements(component_id, [], None)
    incoming = sum(m.qty for m in arrivals)

    print(f"  {'signed order book, next 60 days':<40}{demand:>9,}")
    print(f"  {'usable stock':<40}{stock:>9,}")
    for m in arrivals:
        print(f"  {m.ref + ' arriving ' + str(m.when):<40}{m.qty:>9,}")
    print(f"  {'-' * 49}")
    print(f"  {'expected supply':<40}{stock + incoming:>9,}")
    print(f"  {'gap':<40}{stock + incoming - demand:>9,}")
    print()
    print("  Nothing is flagged. The signed order book is covered exactly.")
    print("  (No forecast yet -- that arrives in act 2.)")


def _wrap(text: str, width: int):
    words, line, out = (text or "").split(), "", []
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
