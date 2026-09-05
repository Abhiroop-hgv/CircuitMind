"""
Run the Intelligence Agent over every unanalysed external event.

    python scripts/run_intelligence.py                 # real model (needs an API key)
    python scripts/run_intelligence.py --offline       # fixtures, no API calls
    python scripts/run_intelligence.py --reset         # mark events NEW and rerun

--offline swaps ONLY the language steps for hand-written fixtures, so the
matching and scoring code is exercised exactly as it runs for real. Rows it
writes are tagged extractor='fixture'.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Models write real typography -- en dashes, narrow no-break spaces. The Windows
# console defaults to cp1252 and raises on those, which would crash a run after
# the work is already done and saved. Print UTF-8 and never die on a character.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.intelligence.agent import IntelligenceAgent, handoff  # noqa: E402
from agents.intelligence.extract import FixtureExtractor, LLMExtractor  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="use hand-written fixtures instead of calling a model")
    ap.add_argument("--groq", action="store_true",
                    help="read the articles with a hosted model on Groq (needs GROQ_API_KEY)")
    ap.add_argument("--local", action="store_true",
                    help="read the articles with a local model via Ollama (no API key)")
    ap.add_argument("--model", default=None,
                    help="override the model id for --groq or --local")
    ap.add_argument("--only", default=None,
                    help="analyse a single event by external_id -- one API call, for a live demo")
    ap.add_argument("--explain", action="store_true",
                    help="also have the model write a sentence per finding "
                         "(off by default: it roughly quadruples the run time, "
                         "and the numbers carry the story on their own)")
    ap.add_argument("--reset", action="store_true",
                    help="set every event back to NEW and clear prior impacts first")
    args = ap.parse_args()

    with connect() as conn:
        if args.reset:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM platform.event_impacts")
                cur.execute(
                    "UPDATE platform.external_events "
                    "SET status = 'NEW', extracted = '{}'::jsonb"
                )
            conn.commit()
            print("reset: all events back to NEW\n")

        explainer = None
        if args.offline:
            extractor = FixtureExtractor()
            explain = False
        elif args.groq:
            from agents.intelligence.groq_extract import DEFAULT_MODEL, GroqExtractor

            extractor = GroqExtractor(model=args.model or DEFAULT_MODEL)
            explainer = extractor.explain
            explain = args.explain
        elif args.local:
            from agents.intelligence.local_extract import OllamaExtractor

            extractor = OllamaExtractor(model=args.model or "qwen2.5:3b")
            installed = extractor.available_models()
            if extractor.model not in installed:
                print(f"model '{extractor.model}' is not installed in Ollama.")
                print(f"installed: {', '.join(installed) or 'none'}")
                print(f"run:  ollama pull {extractor.model}")
                return 1
            explainer = extractor.explain
            explain = args.explain
        else:
            extractor = LLMExtractor()
            explain = args.explain

        agent = IntelligenceAgent(conn, extractor, explain=explain, explainer=explainer)

        events = agent.pending_events()
        if args.only:
            events = [e for e in events if e["external_id"] == args.only]
            if not events:
                print(f"no unanalysed event with external_id '{args.only}'. "
                      f"Add --reset to put the events back to NEW.")
                return 1
        if not events:
            print("nothing to analyse. Use --reset to run again.")
            return 0

        print(f"extractor: {extractor.name}")
        print(f"horizon  : {agent.today} .. {agent.horizon_end}\n")

        flagged = []
        for event in events:
            outcome = agent.analyse(event)
            _report(outcome)
            if outcome.impacts:
                flagged.append(outcome)

        print(RULE)
        print(f"{len(events)} events in, {len(flagged)} with company-specific impact")
        print(RULE)

        for outcome in flagged:
            rows = handoff(conn, outcome.event_id)
            if not rows:
                continue
            print(f"\nhandoff to Supply Risk Agent -- from {outcome.external_id}:")
            for r in rows:
                # No stated timeframe is not the same as no delay. We refuse to
                # invent a number, so the shipment is passed on as "assume it
                # does not land inside the horizon" -- the conservative reading,
                # and one the next agent can act on.
                if r["match_basis"] == "PART_ORIGIN":
                    # Nothing to delay: the goods already in transit were built
                    # before the fab stopped. What is at risk is the next order.
                    print(f"  {r['mpn']:<19} replenishment at risk -- made in "
                          f"{r['origin_country']}, no shipment of ours in that lane "
                          f"({r['risk_level']})")
                    continue
                delay = (f"~{r['expected_delay_days']} days"
                         if r["expected_delay_days"] is not None
                         else "duration not stated -> assume it misses the horizon")
                print(f"  {r['mpn']:<19} treat POs {r['at_risk_po_ids']} as late "
                      f"by {delay}  ({r['at_risk_qty']} units, {r['risk_level']})")
    print()
    return 0


def _report(outcome) -> None:
    e = outcome.extraction
    print(RULE)
    print(f"{outcome.external_id}  {outcome.headline[:60]}")
    print(RULE)
    print(f"  read as        : {e.event_type}  (confidence {e.confidence})")
    print(f"  physical supply: {e.affects_physical_supply}")
    print(f"  geography      : {', '.join(e.countries) or '-'}"
          f"{'  /  ' + ', '.join(e.cities) if e.cities else ''}")
    print(f"  categories     : {', '.join(e.component_categories) or '-'}")
    if e.effective_date:
        print(f"  effective      : {e.effective_date}")
    if e.expected_delay_days is not None:
        print(f"  delay          : ~{e.expected_delay_days} days")

    if not outcome.impacts:
        reason = outcome.result.skipped_reason or "no impact found"
        if outcome.result.supplier_names:
            print(f"  suppliers hit  : {', '.join(n[:34] for n in outcome.result.supplier_names)}")
        print(f"  -> NO IMPACT   : {reason}")
        print()
        return

    print(f"  suppliers hit  : {', '.join(n[:34] for n in outcome.result.supplier_names)}")
    print()
    for impact in outcome.impacts:
        m = impact["match"]
        ri = impact["rule_inputs"]
        why = ("made in " + m.origin_country if m.basis == "PART_ORIGIN"
               else "supplier lane" if m.basis == "SUPPLIER_LANE"
               else "supplier lane + made in " + m.origin_country)
        print(f"  [{impact['risk_level']:<6}] {m.mpn}  ({m.category})  via {why}")
        print(f"            boards   : {', '.join(m.product_skus) or 'none fitted'}")
        source = (", ".join(n[:30] for n in m.supplier_names)
                  or "no supplier of ours there -- exposure is at the fab")
        print(f"            from     : {source}")
        print(f"            in flight: {m.at_risk_qty} units on PO {m.at_risk_po_ids or '-'}")
        print(f"            elsewhere: {ri['unaffected_supplier_stock']} units across "
              f"{ri['unaffected_supplier_count']} unaffected suppliers")
        print(f"            rule     : {ri['rule']}")
        if impact["explanation"]:
            print(f"            says     : {impact['explanation']}")
        print()


if __name__ == "__main__":
    raise SystemExit(main())
