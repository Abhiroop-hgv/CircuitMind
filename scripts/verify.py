"""
Proves the seeded database actually supports the demo story, using plain SQL
only. No agents, no LLM, no forecasting -- this is a data check.

    python scripts/verify.py

If the numbers printed here are wrong, every agent built on top will be wrong
too, so this is the thing to keep green.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.connection import connect  # noqa: E402

TODAY = date(2026, 9, 3)
HORIZON_END = TODAY + timedelta(days=60)
CRITICAL_MPN = "STM32F407VGT6"

RULE = "-" * 78


def head(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def main() -> int:
    with connect() as conn, conn.cursor() as cur:

        head("1. row counts")
        for table in (
            "erp.warehouses", "erp.products", "erp.components", "erp.bom",
            "erp.suppliers", "erp.supplier_components", "erp.inventory",
            "erp.customer_orders", "erp.production_plans",
            "erp.purchase_orders", "erp.purchase_order_items",
            "platform.external_events",
        ):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"  {table:<32} {cur.fetchone()[0]:>7}")

        head("2. the external signal (raw, unanalysed)")
        cur.execute(
            """SELECT id, published_at::date, headline
                 FROM platform.external_events ORDER BY published_at DESC"""
        )
        for eid, pub, headline in cur.fetchall():
            print(f"  [{eid}] {pub}  {headline[:66]}")
        print("\n  extracted column is empty on purpose -- that is the Intelligence Agent's job.")

        head("3. trace: China -> supplier -> component -> product")
        cur.execute(
            """SELECT s.name, c.mpn, p.sku, p.name
                 FROM erp.suppliers s
                 JOIN erp.supplier_components sc ON sc.supplier_id = s.id
                 JOIN erp.components c  ON c.id = sc.component_id
                 JOIN erp.bom b         ON b.component_id = c.id
                 JOIN erp.products p    ON p.id = b.product_id
                WHERE s.country = 'China'
                ORDER BY s.name, c.mpn, p.sku"""
        )
        for name, mpn, sku, product in cur.fetchall():
            print(f"  {name[:38]:<38} {mpn:<16} {sku:<8} {product}")

        head(f"4. supply position for {CRITICAL_MPN} over the next 60 days")
        cur.execute(
            """SELECT COALESCE(SUM(b.qty_per_unit * o.quantity), 0)::int
                 FROM erp.customer_orders o
                 JOIN erp.bom b        ON b.product_id = o.product_id
                 JOIN erp.components c ON c.id = b.component_id
                WHERE c.mpn = %s
                  AND o.requested_delivery_date BETWEEN %s AND %s
                  AND o.status IN ('CONFIRMED', 'OPEN')""",
            (CRITICAL_MPN, TODAY, HORIZON_END),
        )
        demand = cur.fetchone()[0]

        cur.execute(
            "SELECT on_hand, reserved, safety_stock, available "
            "FROM platform.v_stock_position WHERE mpn = %s",
            (CRITICAL_MPN,),
        )
        on_hand, reserved, safety, available = cur.fetchone()

        cur.execute(
            """SELECT po.po_number, s.name, s.country, po.expected_date,
                      (i.quantity - i.received_qty) AS outstanding
                 FROM erp.purchase_order_items i
                 JOIN erp.purchase_orders po ON po.id = i.po_id
                 JOIN erp.suppliers s        ON s.id = po.supplier_id
                 JOIN erp.components c       ON c.id = i.component_id
                WHERE c.mpn = %s AND po.status IN ('OPEN', 'PARTIAL')
                  AND po.expected_date <= %s""",
            (CRITICAL_MPN, HORIZON_END),
        )
        open_pos = cur.fetchall()
        incoming = sum(row[4] for row in open_pos)

        print(f"  committed demand (order book x BOM)   {demand:>8}")
        print(f"  on hand                               {on_hand:>8}")
        print(f"  less reserved                        -{reserved:>8}")
        print(f"  less safety stock                    -{safety:>8}")
        print(f"  usable stock                          {available:>8}")
        for po, supplier, country, expected, qty in open_pos:
            print(f"  open PO {po} {supplier[:26]:<26} {country:<8} due {expected}  {qty:>6}")
        print(f"  expected supply (stock + open POs)     {available + incoming:>8}")
        print(f"  baseline gap                          {available + incoming - demand:>8}"
              "   <- flat today, so nothing is flagged")

        at_risk = sum(qty for _, _, country, _, qty in open_pos if country == "China")
        print(f"\n  of which shipping from China          {at_risk:>8}")
        print(f"  gap if that shipment is held          {available + incoming - at_risk - demand:>8}"
              "   <- the shortage the demo has to find")

        head("5. candidate pool for a substitution (data check, NOT the agent)")
        cur.execute(
            """SELECT c.mpn, c.manufacturer, c.country_of_origin,
                      c.specs->>'footprint_id', c.specs->>'pinout_family',
                      (c.specs->>'ram_kb')::int, (c.specs->>'temp_max_c')::int,
                      (c.specs->>'vcc_min_v')::numeric
                 FROM erp.components c
                WHERE c.category = 'MCU' AND c.mpn <> %s
                ORDER BY c.mpn""",
            (CRITICAL_MPN,),
        )
        print(f"  {'mpn':<16}{'origin':<10}{'footprint':<24}{'pinout':<16}{'ram':>5}{'tmax':>6}{'vmin':>6}")
        for mpn, _mfr, origin, fp, pinout, ram, tmax, vmin in cur.fetchall():
            print(f"  {mpn:<16}{origin:<10}{fp:<24}{pinout:<16}{ram:>5}{tmax:>6}{vmin:>6}")

        cur.execute(
            """SELECT b.design_constraints
                 FROM erp.bom b
                 JOIN erp.components c ON c.id = b.component_id
                 JOIN erp.products p   ON p.id = b.product_id
                WHERE c.mpn = %s AND p.sku = 'MC-3000'""",
            (CRITICAL_MPN,),
        )
        print("\n  MC-3000 requires:")
        for key, value in cur.fetchone()[0].items():
            print(f"    {key:<24} {value}")
        print("\n  Judged against THAT requirement, some of the parts above pass and some")
        print("  fail. Deciding which is the Component Intelligence Agent's job -- not SQL's.")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
