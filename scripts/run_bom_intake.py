"""
Take in a BOM document and register the board as a product.

    python scripts/run_bom_intake.py samples/sensor_hub_SH-100.csv \
        --sku SH-100 --name "Sensor Hub SH-100" --qty 500 --need-by 2026-11-15

Parses the file, matches every part number against the catalogue, and writes the
board into erp.products + erp.bom so the rest of the system starts watching it.
No model involved -- this is parsing and matching.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.bom_intake.intake import ingest  # noqa: E402
from agents.bom_intake.resolve import EXACT, NORMALISED, UNKNOWN  # noqa: E402
from db.connection import connect  # noqa: E402

RULE = "=" * 78


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="BOM file: csv, tsv, xlsx, pdf or txt")
    ap.add_argument("--sku", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--qty", type=int, required=True, help="how many boards to build")
    ap.add_argument("--need-by", required=True, help="YYYY-MM-DD")
    ap.add_argument("--no-register", action="store_true",
                    help="parse and resolve only; do not write to erp.products")
    args = ap.parse_args()

    need_by = datetime.strptime(args.need_by, "%Y-%m-%d").date()

    with connect() as conn:
        intake = ingest(conn, args.file, sku=args.sku, name=args.name,
                        build_qty=args.qty, need_by=need_by,
                        register=not args.no_register)

        c = intake.counts
        print(RULE)
        print(f"{intake.name}  ({intake.sku})")
        print(f"from {intake.filename} -- build {intake.build_qty:,} by {intake.need_by}")
        print(RULE)
        print(f"  {c['total']} lines parsed: {c[EXACT]} exact, "
              f"{c[NORMALISED]} matched after normalising, {c[UNKNOWN]} unknown\n")

        print(f"  {'ref':<6}{'part number':<24}{'per board':>10}  match")
        for line in intake.lines:
            mark = {EXACT: "ok", NORMALISED: "~", UNKNOWN: "NOT FOUND"}[line.resolution]
            print(f"  {line.reference_designator:<6}{line.mpn_raw:<24}"
                  f"{line.quantity_per_board:>10}  {mark}")
            if line.note and line.resolution != EXACT:
                print(f"        {line.note}")

        print()
        if intake.unknown:
            print(f"  {len(intake.unknown)} line(s) could not be matched and are NOT in the")
            print("  registered BOM. The board is registered without them, and any build")
            print("  check will understate what you need until they are resolved:")
            for line in intake.unknown:
                print(f"    {line.reference_designator:<6}{line.mpn_raw:<24}{line.description[:34]}")
            print()

        if intake.product_id:
            print(f"  registered as erp.products id={intake.product_id} "
                  f"with {len(intake.resolved)} BOM lines  [{intake.status}]")
            print("  It is now a normal product: the news monitor, the forecaster and")
            print("  the shortage calculation all see it from here on.")
        else:
            print("  not registered (--no-register)")
        print(RULE)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
