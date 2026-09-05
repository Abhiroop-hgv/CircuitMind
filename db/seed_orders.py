"""
Generates the bulk / transactional half of the dummy ERP:

  * 24 months of shipped customer orders  -> the demand forecaster needs history
  * confirmed orders inside the planning horizon -> committed demand
  * production plans covering the horizon
  * inventory for every component except the one the demo pins by hand
  * supplier offers for everything except the MCUs pinned by hand

Everything is deterministic (fixed RNG seed) so the demo tells the same story
every single run. Master data lives in seed_master.sql; this file only fills in
the volume around it.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

RNG_SEED = 20260903
TODAY = date(2026, 9, 3)
HORIZON_DAYS = 60
HORIZON_END = TODAY + timedelta(days=HORIZON_DAYS)

HISTORY_MONTHS = 24  # 2024-09 .. 2026-08

# product_id -> (starting monthly volume, monthly growth rate)
DEMAND_PROFILE = {
    1: (2100, 0.018),  # MC-3000
    2: (900, 0.011),   # IG-500
    3: (1400, 0.009),  # PI-750
    4: (1150, 0.016),  # SD-220
}

# Committed order book inside the horizon. Chosen to sit close to where the
# history trend lands, so the forecast and the order book corroborate rather
# than contradict each other.
#
#   MC-3000 6,500 x 1 STM32F407VGT6
# + SD-220  3,500 x 1 STM32F407VGT6
# = 10,000 units of demand for the part the demo disrupts.
HORIZON_COMMITTED = {1: 6500, 2: 2300, 3: 3400, 4: 3500}

# mild, repeating seasonality by calendar month
SEASONALITY = {
    1: 0.94, 2: 0.97, 3: 1.05, 4: 1.02, 5: 1.00, 6: 0.98,
    7: 0.95, 8: 0.99, 9: 1.04, 10: 1.06, 11: 1.03, 12: 0.97,
}

CUSTOMERS = [
    "Vertex Automation GmbH",
    "Kirloskar Drives Pvt Ltd",
    "Nordwind Robotics AB",
    "Tanaka Factory Systems KK",
    "Cerro Verde Controles SA",
    "Brightline Industrial Inc",
    "Aurora Motion Systems",
    "Delta Kinetics Ltd",
]

# Components deliberately left out of stock: they are approved alternatives that
# this company does not currently fit on any board. You do not warehouse a part
# you do not use -- which is precisely why a substitution needs a purchase.
NOT_STOCKED = {2, 3, 5, 6, 13, 15, 18, 22, 29}


def _month_start(base: date, offset: int) -> date:
    y, m = divmod((base.year * 12 + base.month - 1) + offset, 12)
    return date(y, m + 1, 1)


def _split_exact(total: int, parts: int, rng: random.Random) -> list[int]:
    """Split total into `parts` positive ints that sum to exactly total."""
    cuts = sorted(rng.sample(range(1, total), parts - 1)) if parts > 1 else []
    out, prev = [], 0
    for c in cuts + [total]:
        out.append(c - prev)
        prev = c
    return out


# ---------------------------------------------------------------------------
# customer orders
# ---------------------------------------------------------------------------

def _seed_customer_orders(cur, rng: random.Random) -> None:
    rows = []
    seq = 0
    history_start = _month_start(TODAY, -HISTORY_MONTHS)

    for offset in range(HISTORY_MONTHS):
        month = _month_start(history_start, offset)
        for product_id, (base, growth) in DEMAND_PROFILE.items():
            trend = base * ((1 + growth) ** offset)
            volume = trend * SEASONALITY[month.month] * rng.uniform(0.96, 1.04)
            volume = int(round(volume))

            for qty in _split_exact(volume, rng.randint(3, 6), rng):
                seq += 1
                order_day = month + timedelta(days=rng.randint(0, 26))
                rows.append((
                    f"SO-{month:%Y%m}-{seq:05d}",
                    rng.choice(CUSTOMERS),
                    product_id,
                    qty,
                    order_day,
                    order_day + timedelta(days=rng.randint(25, 45)),
                    "SHIPPED",
                ))

    # committed order book inside the horizon
    for product_id, total in HORIZON_COMMITTED.items():
        for qty in _split_exact(total, rng.randint(4, 7), rng):
            seq += 1
            order_day = TODAY - timedelta(days=rng.randint(3, 30))
            delivery = TODAY + timedelta(days=rng.randint(10, HORIZON_DAYS))
            rows.append((
                f"SO-{TODAY:%Y%m}-{seq:05d}",
                rng.choice(CUSTOMERS),
                product_id,
                qty,
                order_day,
                delivery,
                "CONFIRMED" if delivery <= TODAY + timedelta(days=40) else "OPEN",
            ))

    cur.executemany(
        """INSERT INTO erp.customer_orders
             (order_no, customer_name, product_id, quantity,
              order_date, requested_delivery_date, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        rows,
    )
    print(f"  customer_orders      {len(rows):>6}")


# ---------------------------------------------------------------------------
# production plans
# ---------------------------------------------------------------------------

def _seed_production_plans(cur) -> None:
    rows = []
    for product_id, total in HORIZON_COMMITTED.items():
        for offset, share in ((0, 0.5), (1, 0.5)):
            start = _month_start(TODAY, offset)
            end = _month_start(TODAY, offset + 1) - timedelta(days=1)
            rows.append((product_id, int(round(total * share)), start, end, "PLANNED"))

    cur.executemany(
        """INSERT INTO erp.production_plans
             (product_id, planned_qty, period_start, period_end, status)
           VALUES (%s, %s, %s, %s, %s)""",
        rows,
    )
    print(f"  production_plans     {len(rows):>6}")


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------

def _horizon_component_demand(cur) -> dict[int, int]:
    """Explode the committed order book through the BOM."""
    cur.execute(
        """SELECT b.component_id, SUM(b.qty_per_unit * o.quantity)::int
             FROM erp.customer_orders o
             JOIN erp.bom b ON b.product_id = o.product_id
            WHERE o.requested_delivery_date BETWEEN %s AND %s
              AND o.status IN ('CONFIRMED', 'OPEN')
            GROUP BY b.component_id""",
        (TODAY, HORIZON_END),
    )
    return dict(cur.fetchall())


def _seed_inventory(cur, demand: dict[int, int]) -> None:
    """
    Stock every other component comfortably. The demo must show exactly ONE
    shortage -- the one the external event causes. A second, unrelated shortage
    would just be noise on stage.
    """
    rows = []
    for component_id, qty in sorted(demand.items()):
        if component_id == 1 or component_id in NOT_STOCKED:
            continue  # component 1 is pinned by hand in seed_master.sql
        warehouse = 1 if component_id % 3 else 2
        rows.append((
            component_id,
            warehouse,
            int(qty * 1.6) + 500,
            int(qty * 0.08),
            int(qty * 0.05),
        ))

    cur.executemany(
        """INSERT INTO erp.inventory
             (component_id, warehouse_id, quantity, reserved_quantity, safety_stock)
           VALUES (%s, %s, %s, %s, %s)""",
        rows,
    )
    print(f"  inventory            {len(rows):>6}")


# ---------------------------------------------------------------------------
# supplier offers
# ---------------------------------------------------------------------------

def _seed_supplier_components(cur, rng: random.Random) -> None:
    """
    Offers for everything the MCU block in seed_master.sql does not cover.
    Price is anchored to standard cost; distributors carry a mark-up, the
    manufacturers undercut them but ship slowly.
    """
    cur.execute(
        """SELECT id, standard_cost FROM erp.components
            WHERE id NOT IN (SELECT DISTINCT component_id FROM erp.supplier_components)
            ORDER BY id"""
    )
    components = cur.fetchall()

    cur.execute("SELECT id, supplier_type, avg_lead_time_days FROM erp.suppliers ORDER BY id")
    suppliers = cur.fetchall()

    rows = []
    for component_id, cost in components:
        for supplier_id, supplier_type, base_lead in rng.sample(suppliers, rng.randint(2, 4)):
            markup = rng.uniform(1.12, 1.35) if supplier_type == "DISTRIBUTOR" else rng.uniform(0.88, 1.02)
            lead = max(3, int(base_lead * rng.uniform(0.8, 1.25)))
            moq = 1 if supplier_type == "DISTRIBUTOR" else rng.choice([500, 1000, 2500])
            rows.append((
                supplier_id,
                component_id,
                round(float(cost) * markup, 4),
                lead,
                moq,
                int(rng.uniform(4000, 60000)) if float(cost) < 1 else int(rng.uniform(500, 9000)),
            ))

    cur.executemany(
        """INSERT INTO erp.supplier_components
             (supplier_id, component_id, unit_price, lead_time_days, moq, stock_available)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        rows,
    )
    print(f"  supplier_components  {len(rows):>6}  (+20 MCU offers from seed_master.sql)")


# ---------------------------------------------------------------------------

def _seed_delivery_history(cur, rng: random.Random) -> None:
    """
    Closed purchase orders going back 18 months, with the date the goods
    actually turned up.

    Each supplier gets a behaviour profile -- how often they hit the promised
    date, and by how much they miss when they do. This is what the reliability
    score is computed from; without a delivery history the score would have
    nothing to stand on.

    Mouser is deliberately the cheapest supplier AND the least punctual. That
    tension is the whole point of scoring: the lowest unit price is not the
    lowest total cost when the parts arrive after the line has stopped.
    """
    # supplier_id -> (on-time probability, typical days late when late)
    behaviour = {
        1:  (0.70, 12),   # Shenzhen Ruiyang
        2:  (0.80, 5),    # TaiChip
        3:  (0.93, 2),    # Nexperia
        4:  (0.95, 1),    # DigiKey
        5:  (0.55, 8),    # Mouser -- cheapest, and the worst at dates
        6:  (0.90, 2),    # Arrow
        7:  (0.88, 3),    # Avnet
        8:  (0.60, 15),   # Fujian Longtai
        9:  (0.85, 4),    # Hanwoo
        10: (0.92, 2),    # Rutronik
    }

    cur.execute("SELECT id FROM erp.components ORDER BY id")
    component_ids = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT id, avg_lead_time_days FROM erp.suppliers ORDER BY id")
    lead_times = dict(cur.fetchall())

    po_id, po_rows, item_rows = 100, [], []
    for supplier_id, (on_time_p, typical_late) in behaviour.items():
        for _ in range(rng.randint(11, 15)):
            ordered = TODAY - timedelta(days=rng.randint(40, 540))
            lead = max(3, int(lead_times[supplier_id] * rng.uniform(0.85, 1.15)))
            expected = ordered + timedelta(days=lead)

            if rng.random() < on_time_p:
                # on time, and often a day or two early
                actual = expected - timedelta(days=rng.randint(0, 2))
            else:
                slip = max(1, int(rng.gauss(typical_late, typical_late * 0.4)))
                actual = expected + timedelta(days=slip)

            po_id += 1
            po_rows.append((po_id, f"PO-HIST-{po_id}", supplier_id, "RECEIVED",
                            ordered, expected, actual))
            qty = rng.choice([500, 1000, 2000, 2500, 5000])
            item_rows.append((po_id, rng.choice(component_ids), qty, qty,
                              round(rng.uniform(0.05, 12.0), 4)))

    cur.executemany(
        """INSERT INTO erp.purchase_orders
             (id, po_number, supplier_id, status, order_date, expected_date,
              actual_receipt_date)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        po_rows,
    )
    cur.executemany(
        """INSERT INTO erp.purchase_order_items
             (po_id, component_id, quantity, received_qty, unit_price)
           VALUES (%s,%s,%s,%s,%s)""",
        item_rows,
    )
    print(f"  delivery history     {len(po_rows):>6}  closed POs across 10 suppliers")


def seed(conn) -> None:
    rng = random.Random(RNG_SEED)
    with conn.cursor() as cur:
        _seed_customer_orders(cur, rng)
        _seed_production_plans(cur)
        demand = _horizon_component_demand(cur)
        _seed_inventory(cur, demand)
        _seed_supplier_components(cur, rng)
        _seed_delivery_history(cur, rng)
    conn.commit()
