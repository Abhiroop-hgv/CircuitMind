"""
Exercises every assistant tool, including the paths that are meant to fail.

The interesting cases are the unhappy ones. A tool that returns a clean answer
for a good input but throws for a bad one hands the model a stack trace, and a
model given a stack trace will say something strange to the user.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agents.assistant import tools as T          # noqa: E402
from db.connection import connect                # noqa: E402

CASES = [
    ("find_component / exact",        "find_component", {"part": "STM32F407VGT6"}),
    ("find_component / prefix",       "find_component", {"part": "STM32F4"}),
    ("find_component / synonym",      "find_component", {"part": "controller chip"}),
    ("find_component / unknown",      "find_component", {"part": "ACME-9000"}),
    ("find_component / empty",        "find_component", {"part": ""}),
    ("find_component / sql-ish",      "find_component", {"part": "'; DROP TABLE erp.components; --"}),

    ("stock_position / ok",           "stock_position", {"part": "STM32F407VGT6"}),
    ("stock_position / not stocked",  "stock_position", {"part": "STM32F429VGT6"}),
    ("stock_position / unknown",      "stock_position", {"part": "ACME-9000"}),

    ("demand_forecast / all months",  "demand_forecast", {"part": "STM32F407VGT6"}),
    ("demand_forecast / one month",   "demand_forecast", {"part": "STM32F407VGT6", "month": "2026-09"}),
    ("demand_forecast / empty month", "demand_forecast", {"part": "STM32F407VGT6", "month": "1999-01"}),
    ("demand_forecast / null month",  "demand_forecast", {"part": "STM32F407VGT6", "month": None}),
    ("demand_forecast / junk month",  "demand_forecast", {"part": "STM32F407VGT6", "month": "September"}),

    ("events / all",                  "events_affecting_inventory", {}),
    ("events / HIGH",                 "events_affecting_inventory", {"risk": "HIGH"}),
    ("events / lowercase",            "events_affecting_inventory", {"risk": "high"}),
    ("events / null",                 "events_affecting_inventory", {"risk": None}),
    ("events / bogus risk",           "events_affecting_inventory", {"risk": "SEVERE"}),

    ("stock_ledger / ok",             "stock_ledger", {"part": "STM32F407VGT6"}),
    ("stock_ledger / no analysis",    "stock_ledger", {"part": "AMS1117-3.3"}),
    ("stock_ledger / unknown",        "stock_ledger", {"part": "ACME-9000"}),

    ("list_suppliers / all",          "list_suppliers", {}),
    ("list_suppliers / country",      "list_suppliers", {"country": "china"}),
    ("list_suppliers / type",         "list_suppliers", {"supplier_type": "manufacturer"}),
    ("list_suppliers / nulls",        "list_suppliers", {"country": None, "supplier_type": None}),
    ("list_suppliers / bogus",        "list_suppliers", {"country": "Atlantis"}),

    ("reliability / all",             "supplier_reliability", {}),
    ("reliability / named",           "supplier_reliability", {"supplier": "Mouser"}),
    ("reliability / partial",         "supplier_reliability", {"supplier": "mous"}),
    ("reliability / null",            "supplier_reliability", {"supplier": None}),
    ("reliability / unknown",         "supplier_reliability", {"supplier": "Nobody Ltd"}),

    ("inventory / all",               "inventory_overview", {}),
    ("inventory / country",           "inventory_overview", {"country": "China"}),
    ("inventory / category",          "inventory_overview", {"category": "mcu"}),
    ("inventory / nulls",             "inventory_overview", {"country": None, "category": None}),
    ("inventory / bogus",            "inventory_overview", {"country": "Atlantis"}),

    ("current_shortages",             "current_shortages", {}),
    ("pending_recommendations",       "pending_recommendations", {}),
]


def main() -> int:
    conn = connect()
    passed = failed = 0

    for label, name, args in CASES:
        fn = T.REGISTRY[name]
        try:
            out = fn(conn, **args)
        except Exception as exc:                      # noqa: BLE001
            print(f"  THREW  {label:32} {type(exc).__name__}: {exc}")
            failed += 1
            continue

        if not isinstance(out, dict):
            print(f"  BAD    {label:32} returned {type(out).__name__}, not a dict")
            failed += 1
            continue

        kind = "error" if "error" in out else ("note" if set(out) == {"note"} else "data")
        detail = out.get("error") or out.get("note") or ""
        print(f"  ok     {label:32} [{kind}] {str(detail)[:58]}")
        passed += 1

    conn.close()
    print(f"\n  {passed} handled, {failed} threw")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
