"""
What do we do about the part numbers that did not match?

    python scripts/run_suggest.py            # text ranking only, no network
    python scripts/run_suggest.py --llm      # also ask the model what the part is

For every UNKNOWN line on a build request, rank the catalogue by text similarity
and, with --llm, ask what class of part it actually is.

Nothing here resolves anything. It produces a shortlist for a person. Text
similarity is not understanding -- "Dual op-amp SOIC-8" and "Operational
amplifier, 8-pin small outline" share almost no words -- so a confident-looking
automatic match would be the worst possible outcome.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.bom_intake.similarity import rank  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78


def catalogue(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, mpn, manufacturer, category, description, specs,
                      standard_cost
                 FROM erp.components WHERE lifecycle = 'ACTIVE' ORDER BY mpn"""
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def unknown_lines(conn, request_id=None):
    sql = """SELECT l.id, l.request_id, l.line_number, l.reference_designator,
                    l.mpn_raw, l.description, l.quantity_per_board, r.product_sku
               FROM platform.build_request_lines l
               JOIN platform.build_requests r ON r.id = l.request_id
              WHERE l.resolution = 'UNKNOWN'"""
    params = ()
    if request_id:
        sql += " AND l.request_id = %s"
        params = (request_id,)
    sql += " ORDER BY l.request_id, l.line_number"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", type=int, default=None)
    ap.add_argument("--llm", action="store_true", help="ask the model what the part is")
    args = ap.parse_args()

    with connect() as conn:
        lines = unknown_lines(conn, args.request)
        if not lines:
            print("no unmatched part numbers. Nothing to suggest.")
            return 0

        parts = catalogue(conn)
        categories = sorted({p["category"] for p in parts})

        identify = None
        if args.llm:
            from agents.intelligence.groq_extract import GroqExtractor, identify_part
            extractor = GroqExtractor()
            identify = lambda mpn, desc: identify_part(extractor, mpn, desc, categories)  # noqa: E731

        for line in lines:
            print(RULE)
            print(f"{line['product_sku']} line {line['line_number']} "
                  f"({line['reference_designator']}): {line['mpn_raw']}")
            print(f"document said: {line['description'] or '(no description)'}")
            print(RULE)

            identified = None
            if identify:
                identified = identify(line["mpn_raw"], line["description"])
                print(f"  the model says: {identified['what_it_is']}")
                print(f"  function      : {identified['function']}")
                print(f"  category      : {identified['category']}"
                      f"   (confidence {identified['confidence']})")
                print()

            query = f"{line['mpn_raw']} {line['description']}"
            top = rank(query, parts, top_k=5)

            print("  closest things in the catalogue, by text similarity:")
            for row, score in top:
                print(f"    {score:>6.3f}  {row['mpn']:<24}{row['category']:<18}"
                      f"{(row['description'] or '')[:30]}")
            print()

            # ---- the verdict, and it is deliberately blunt -------------------
            if identified and identified["category"] == "NONE":
                print("  VERDICT: we stock no part of this class at all.")
                print("  Nothing above is a substitute -- they are the least dissimilar")
                print("  rows in a catalogue that has no equivalent. This part has to be")
                print("  added to the catalogue and sourced on its own merits.")
            elif identified:
                same = [r for r, _ in top if r["category"] == identified["category"]]
                if same:
                    print(f"  VERDICT: we do stock {identified['category']} parts. "
                          f"Worth an engineer's eye:")
                    for row in same:
                        print(f"    {row['mpn']}  ({row['description'][:44]})")
                else:
                    print(f"  VERDICT: the model puts this in {identified['category']}, "
                          f"but nothing")
                    print("  of that category ranked. Treat the list above as noise.")
            else:
                best = top[0][1] if top else 0.0
                if best < 0.25:
                    print("  VERDICT: nothing scores above 0.25. Text overlap alone cannot")
                    print("  tell you whether an equivalent exists -- rerun with --llm, or")
                    print("  put this line in front of an engineer.")
                else:
                    print("  VERDICT: candidates above are worth a look. Text similarity is")
                    print("  shared vocabulary, not shared function -- confirm before using.")
            print()

        print(RULE)
        print("  Nothing was resolved automatically. A person decides what these are.")
        print(RULE)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
