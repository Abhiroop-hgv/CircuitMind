"""
The Supply Risk Agent.

Agent 1 said "4,000 units are stuck". This one answers the question that
follows: do we actually run out, how many, and from what date?

There is NO language model in this file, and that is deliberate. This number
ends up on a purchase order. It has to come out identical every time it is
computed, and a buyer has to be able to reproduce it on paper in the review
meeting. So it is arithmetic, and the working is saved alongside the answer.

The method is a running stock ledger rather than a single subtraction:

    start at usable stock
    walk forward through the horizon, date by date
    subtract each customer order as it comes due
    add each purchase order as it lands
    the lowest the balance ever gets is what we are short

Timing is the whole point. Demand minus supply across a whole quarter can come
out flat while you still run dry in week three, because the parts arrive after
the boards were due. A single subtraction cannot see that; a ledger can.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from psycopg.types.json import Jsonb

from agents.demand.agent import uncovered_demand

HORIZON_DAYS = 60


@dataclass
class Movement:
    when: date
    qty: int              # negative for demand, positive for arrivals
    kind: str             # DEMAND | ARRIVAL | ARRIVAL_DELAYED
    ref: str
    note: str = ""


@dataclass
class Shortage:
    component_id: int
    mpn: str
    horizon_start: date
    horizon_end: date
    demand_qty: int = 0
    usable_stock: int = 0
    incoming_on_time: int = 0
    incoming_delayed: int = 0
    incoming_lost: int = 0
    shortage_qty: int = 0
    first_shortfall_date: Optional[date] = None
    severity: str = "NONE"
    baseline_shortage_qty: int = 0
    ledger: List[Dict] = field(default_factory=list)

    @property
    def expected_supply(self) -> int:
        return self.usable_stock + self.incoming_on_time + self.incoming_delayed


class SupplyRiskAgent:
    def __init__(self, conn, today: Optional[date] = None, use_forecast: bool = True,
                 horizon_end: Optional[date] = None):
        self.conn = conn
        self.today = today or date(2026, 9, 3)
        # A news event is assessed over a rolling 60 days. A build request is
        # assessed to its own need-by date, which is why this is overridable.
        self.horizon_end = horizon_end or (self.today + timedelta(days=HORIZON_DAYS))
        self.use_forecast = use_forecast

    # -- inputs ------------------------------------------------------------

    def handoffs(self, event_id: Optional[int] = None) -> List[Dict]:
        """What agent 1 flagged. Without an event id, take everything open."""
        sql = """SELECT i.event_id, i.component_id, c.mpn, i.at_risk_po_ids,
                        i.at_risk_qty, i.expected_delay_days, i.risk_level
                   FROM platform.event_impacts i
                   JOIN erp.components c ON c.id = i.component_id
                  WHERE i.risk_level IN ('HIGH', 'MEDIUM')"""
        params: tuple = ()
        if event_id is not None:
            sql += " AND i.event_id = %s"
            params = (event_id,)
        sql += " ORDER BY i.risk_level, c.mpn"

        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def demand_movements(self, component_id: int) -> List[Movement]:
        """
        Committed customer orders, exploded through the BOM, dated by when the
        customer wants the boards -- plus whatever agent 2 forecasts on top.

        Only the UNCOVERED part of the forecast is added. The committed orders
        are already here as real dated movements, so adding the whole forecast
        would count them twice. If no forecast has been run for this horizon,
        the list comes back empty and we fall back to the order book alone.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT o.requested_delivery_date,
                          (b.qty_per_unit * o.quantity)::int,
                          o.order_no, p.sku
                     FROM erp.customer_orders o
                     JOIN erp.bom b      ON b.product_id = o.product_id
                     JOIN erp.products p ON p.id = o.product_id
                    WHERE b.component_id = %s
                      AND o.status IN ('CONFIRMED', 'OPEN')
                      AND o.requested_delivery_date BETWEEN %s AND %s
                    ORDER BY o.requested_delivery_date""",
                (component_id, self.today, self.horizon_end),
            )
            movements = [
                Movement(when=when, qty=-qty, kind="DEMAND", ref=order_no, note=sku)
                for when, qty, order_no, sku in cur.fetchall()
            ]

        if self.use_forecast:
            for row in uncovered_demand(self.conn, component_id, self.today):
                movements.append(Movement(
                    when=row["when"], qty=-row["qty"], kind="FORECAST",
                    ref=row["month"].strftime("%b %Y"),
                    note="forecast beyond the signed order book (agent 2)",
                ))

        return movements

    def arrival_movements(self, component_id: int, at_risk_po_ids: List[int],
                  delay_days: Optional[int]) -> List[Movement]:
        """
        Open purchase orders, dated by when they are expected.

        A PO agent 1 flagged gets its date pushed out by the delay. If that
        pushes it past the horizon it stops counting as supply -- it is still
        coming, just not in time to help. A flagged PO with no stated delay is
        treated the same way: we will not invent a duration, and assuming it
        misses is the conservative reading.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT po.id, po.po_number, po.expected_date,
                          (i.quantity - i.received_qty)::int, s.name, po.ship_from_country
                     FROM erp.purchase_order_items i
                     JOIN erp.purchase_orders po ON po.id = i.po_id
                     JOIN erp.suppliers s        ON s.id = po.supplier_id
                    WHERE i.component_id = %s
                      AND po.status IN ('OPEN', 'PARTIAL')
                      AND (i.quantity - i.received_qty) > 0
                    ORDER BY po.expected_date""",
                (component_id,),
            )
            rows = cur.fetchall()

        movements = []
        for po_id, po_number, expected, qty, supplier, country in rows:
            if po_id in at_risk_po_ids:
                if delay_days is None:
                    movements.append(Movement(
                        expected, qty, "ARRIVAL_DELAYED", po_number,
                        f"held at {country}, no duration given -- assumed to miss the horizon",
                    ))
                    continue
                shifted = expected + timedelta(days=delay_days)
                movements.append(Movement(
                    shifted, qty, "ARRIVAL_DELAYED", po_number,
                    f"{supplier[:26]} -- was {expected}, +{delay_days}d",
                ))
            elif self.today <= expected <= self.horizon_end:
                movements.append(Movement(
                    expected, qty, "ARRIVAL", po_number, supplier[:26],
                ))
        return movements

    # -- the calculation ---------------------------------------------------

    def usable_stock(self, component_id: int) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT available FROM platform.v_stock_position WHERE component_id = %s",
                (component_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def walk(self, opening: int, movements: List[Movement]) -> tuple:
        """Run the ledger. Returns (peak_shortfall, first_negative_date, rows)."""
        balance = opening
        worst = 0
        first_negative = None
        rows = [{
            "date": str(self.today), "kind": "OPENING", "ref": "usable stock",
            "qty": opening, "balance": balance, "note": "on hand less reserved less safety",
        }]

        for m in sorted(movements, key=lambda x: (x.when, x.kind != "DEMAND")):
            if m.when > self.horizon_end:
                rows.append({
                    "date": str(m.when), "kind": "OUTSIDE_HORIZON", "ref": m.ref,
                    "qty": m.qty, "balance": balance,
                    "note": (m.note + " -- lands after the horizon, not counted").strip(" -"),
                })
                continue

            balance += m.qty
            if balance < worst:
                worst = balance
            if balance < 0 and first_negative is None:
                first_negative = m.when
            rows.append({
                "date": str(m.when), "kind": m.kind, "ref": m.ref,
                "qty": m.qty, "balance": balance, "note": m.note,
            })

        return (-worst if worst < 0 else 0), first_negative, rows

    def assess(self, handoff: Dict) -> Shortage:
        component_id = handoff["component_id"]
        at_risk = list(handoff["at_risk_po_ids"] or [])
        delay = handoff["expected_delay_days"]

        demand = self.demand_movements(component_id)
        opening = self.usable_stock(component_id)

        disrupted = self.arrival_movements(component_id, at_risk, delay)
        baseline = self.arrival_movements(component_id, [], None)  # nothing flagged

        shortage_qty, first_negative, ledger = self.walk(opening, demand + disrupted)
        baseline_qty, _, _ = self.walk(opening, demand + baseline)

        s = Shortage(
            component_id=component_id,
            mpn=handoff["mpn"],
            horizon_start=self.today,
            horizon_end=self.horizon_end,
            demand_qty=-sum(m.qty for m in demand),
            usable_stock=opening,
            shortage_qty=shortage_qty,
            first_shortfall_date=first_negative,
            baseline_shortage_qty=baseline_qty,
            ledger=ledger,
        )

        for m in disrupted:
            if m.when > self.horizon_end:
                s.incoming_lost += m.qty
            elif m.kind == "ARRIVAL_DELAYED":
                s.incoming_delayed += m.qty
            else:
                s.incoming_on_time += m.qty

        s.severity = self._severity(s)
        return s

    @staticmethod
    def _severity(s: Shortage) -> str:
        """
        A stated rule, not a model call. The ratio is what a planner cares
        about: being 40 units short of 10,000 is a phone call, being 4,000
        short is a production stop.
        """
        if s.shortage_qty <= 0:
            return "NONE"
        if s.demand_qty <= 0:
            return "MEDIUM"
        ratio = s.shortage_qty / s.demand_qty
        if ratio >= 0.30:
            return "CRITICAL"
        if ratio >= 0.10:
            return "HIGH"
        return "MEDIUM"

    # -- persistence -------------------------------------------------------

    def persist(self, event_id: Optional[int], s: Shortage) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO platform.shortages
                     (event_id, component_id, horizon_start, horizon_end, demand_qty,
                      usable_stock, incoming_on_time, incoming_delayed, incoming_lost,
                      expected_supply, shortage_qty, first_shortfall_date, severity,
                      baseline_shortage_qty, ledger)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (event_id, component_id) DO UPDATE SET
                     demand_qty=EXCLUDED.demand_qty, usable_stock=EXCLUDED.usable_stock,
                     incoming_on_time=EXCLUDED.incoming_on_time,
                     incoming_delayed=EXCLUDED.incoming_delayed,
                     incoming_lost=EXCLUDED.incoming_lost,
                     expected_supply=EXCLUDED.expected_supply,
                     shortage_qty=EXCLUDED.shortage_qty,
                     first_shortfall_date=EXCLUDED.first_shortfall_date,
                     severity=EXCLUDED.severity,
                     baseline_shortage_qty=EXCLUDED.baseline_shortage_qty,
                     ledger=EXCLUDED.ledger, created_at=NOW()""",
                (event_id, s.component_id, s.horizon_start, s.horizon_end, s.demand_qty,
                 s.usable_stock, s.incoming_on_time, s.incoming_delayed, s.incoming_lost,
                 s.expected_supply, s.shortage_qty, s.first_shortfall_date, s.severity,
                 s.baseline_shortage_qty, Jsonb(s.ledger)),
            )
        self.conn.commit()

    def run(self, event_id: Optional[int] = None) -> List[Shortage]:
        out = []
        for handoff in self.handoffs(event_id):
            s = self.assess(handoff)
            self.persist(handoff["event_id"], s)
            out.append(s)
        return out


def handoff_to_component_agent(conn, event_id: Optional[int] = None) -> List[Dict]:
    """What agent 4 picks up: the parts we are short of, and by how much."""
    sql = """SELECT c.id AS component_id, c.mpn, s.shortage_qty,
                    s.first_shortfall_date, s.severity
               FROM platform.shortages s
               JOIN erp.components c ON c.id = s.component_id
              WHERE s.shortage_qty > 0"""
    params: tuple = ()
    if event_id is not None:
        sql += " AND s.event_id = %s"
        params = (event_id,)
    sql += " ORDER BY s.shortage_qty DESC"

    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
