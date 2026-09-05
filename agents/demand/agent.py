"""
The Demand Forecasting Agent.

Answers "how much will we need?" -- and it is a SUPPORTING agent, not the
headline. Every ERP and SCM suite on the market already forecasts demand, and
does it well. It is here because the shortage calculation needs a demand number.

    order history -> forecasting tool -> BOM explosion -> reconcile with the
    committed order book -> demand across the SAME window agent 3 uses

The agent orchestrates; it does not do arithmetic itself, and it never asks a
language model for a number.

Two things make the output usable by agent 3 rather than merely interesting:

  WINDOW ALIGNMENT. The forecast is monthly, the risk horizon is a rolling 60
  days. A monthly figure is prorated by how many of its days fall inside the
  window, so 3 Sep - 2 Nov takes 28/30 of September, all of October, and 2/30
  of November. Without this the two agents quote different demand for the same
  question, which is the kind of detail that sinks a demo under questioning.

  FORECAST CONSUMPTION. Per month, demand is the GREATER of the committed order
  book and the forecast -- the standard MRP rule. Adding them would double-count
  every order a customer has already placed. Only the UNCOVERED part of the
  forecast (net minus committed) is passed to agent 3, because the committed
  orders are already in its ledger as real dated movements.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from psycopg.types.json import Jsonb

from .forecast import Forecast, forecast

HISTORY_MONTHS = 24
HORIZON_DAYS = 60


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(d: date, n: int) -> date:
    y, m = divmod((d.year * 12 + d.month - 1) + n, 12)
    return date(y, m + 1, 1)


@dataclass
class Segment:
    """One month, and the slice of it that falls inside the horizon."""
    month: date
    start: date
    end: date

    @property
    def days_in_window(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def days_in_month(self) -> int:
        return calendar.monthrange(self.month.year, self.month.month)[1]

    @property
    def share(self) -> float:
        return self.days_in_window / self.days_in_month

    @property
    def midpoint(self) -> date:
        return self.start + timedelta(days=self.days_in_window // 2)


@dataclass
class ProductForecast:
    product_id: int
    sku: str
    history: List[int]
    result: Forecast


@dataclass
class ComponentDemand:
    component_id: int
    mpn: str
    segments: List[Segment]
    committed: List[int] = field(default_factory=list)
    forecast: List[int] = field(default_factory=list)   # already prorated
    net: List[int] = field(default_factory=list)
    drivers: Dict[str, int] = field(default_factory=dict)

    @property
    def uncovered(self) -> List[int]:
        """Forecast demand nobody has ordered yet -- what agent 3 has not seen."""
        return [n - c for n, c in zip(self.net, self.committed)]

    @property
    def total_net(self) -> int:
        return sum(self.net)

    @property
    def total_committed(self) -> int:
        return sum(self.committed)


class DemandAgent:
    def __init__(self, conn, today: Optional[date] = None, horizon_days: int = HORIZON_DAYS):
        self.conn = conn
        self.today = today or date(2026, 9, 3)
        self.horizon_days = horizon_days
        self.horizon_end = self.today + timedelta(days=horizon_days)
        self.first_month = _month_start(self.today)
        self.segments = self._segments()

    def _segments(self) -> List[Segment]:
        """Split the rolling window into month slices."""
        out, cursor = [], self.today
        while cursor <= self.horizon_end:
            month = _month_start(cursor)
            last_day = _add_months(month, 1) - timedelta(days=1)
            end = min(last_day, self.horizon_end)
            out.append(Segment(month=month, start=cursor, end=end))
            cursor = end + timedelta(days=1)
        return out

    # -- history -----------------------------------------------------------

    def _history(self, product_id: int) -> List[int]:
        start = _add_months(self.first_month, -HISTORY_MONTHS)
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT date_trunc('month', order_date)::date, SUM(quantity)::int
                     FROM erp.customer_orders
                    WHERE product_id = %s AND status = 'SHIPPED'
                      AND order_date >= %s AND order_date < %s
                    GROUP BY 1 ORDER BY 1""",
                (product_id, start, self.first_month),
            )
            found = dict(cur.fetchall())
        return [found.get(_add_months(start, i), 0) for i in range(HISTORY_MONTHS)]

    def products(self) -> List[Dict]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, sku, name FROM erp.products WHERE active ORDER BY sku")
            return [{"id": r[0], "sku": r[1], "name": r[2]} for r in cur.fetchall()]

    def forecast_products(self) -> List[ProductForecast]:
        return [
            ProductForecast(product_id=p["id"], sku=p["sku"],
                            history=self._history(p["id"]),
                            result=forecast(self._history(p["id"]), len(self.segments)))
            for p in self.products()
        ]

    # -- explosion and reconciliation --------------------------------------

    def _committed_by_segment(self, component_id: int) -> List[int]:
        out = []
        with self.conn.cursor() as cur:
            for seg in self.segments:
                cur.execute(
                    """SELECT COALESCE(SUM(b.qty_per_unit * o.quantity), 0)::int
                         FROM erp.customer_orders o
                         JOIN erp.bom b ON b.product_id = o.product_id
                        WHERE b.component_id = %s
                          AND o.status IN ('CONFIRMED', 'OPEN')
                          AND o.requested_delivery_date BETWEEN %s AND %s""",
                    (component_id, seg.start, seg.end),
                )
                out.append(cur.fetchone()[0])
        return out

    def explode(self, product_forecasts: List[ProductForecast]) -> List[ComponentDemand]:
        by_product = {pf.product_id: pf for pf in product_forecasts}

        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT b.component_id, c.mpn, b.product_id, p.sku, b.qty_per_unit
                     FROM erp.bom b
                     JOIN erp.components c ON c.id = b.component_id
                     JOIN erp.products p   ON p.id = b.product_id"""
            )
            rows = cur.fetchall()

        demands: Dict[int, ComponentDemand] = {}
        for component_id, mpn, product_id, sku, qty_per in rows:
            pf = by_product.get(product_id)
            if pf is None:
                continue
            d = demands.setdefault(component_id, ComponentDemand(
                component_id=component_id, mpn=mpn, segments=self.segments,
                forecast=[0] * len(self.segments),
            ))
            for i, seg in enumerate(self.segments):
                monthly = pf.result.points[i] if i < len(pf.result.points) else 0
                # prorate the month down to the days inside the window
                d.forecast[i] += int(round(monthly * seg.share * float(qty_per)))
            d.drivers[sku] = d.drivers.get(sku, 0) + int(round(
                sum(pf.result.points[i] * self.segments[i].share
                    for i in range(len(self.segments))) * float(qty_per)))

        for d in demands.values():
            d.committed = self._committed_by_segment(d.component_id)
            d.net = [max(c, f) for c, f in zip(d.committed, d.forecast)]

        return sorted(demands.values(), key=lambda d: -d.total_net)

    # -- persistence -------------------------------------------------------

    def persist(self, demands: List[ComponentDemand],
                product_forecasts: List[ProductForecast]) -> None:
        method = product_forecasts[0].result.method if product_forecasts else "n/a"
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM platform.demand_forecasts WHERE horizon_start = %s",
                        (self.today,))
            for d in demands:
                for i, seg in enumerate(d.segments):
                    cur.execute(
                        """INSERT INTO platform.demand_forecasts
                             (component_id, period_month, horizon_start, committed_qty,
                              forecast_qty, net_demand_qty, method, drivers)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (d.component_id, seg.month, self.today, d.committed[i],
                         d.forecast[i], d.net[i], method,
                         Jsonb({**d.drivers,
                                "_window": f"{seg.start} to {seg.end}",
                                "_share_of_month": round(seg.share, 3)})),
                    )
        self.conn.commit()


def uncovered_demand(conn, component_id: int, horizon_start: date) -> List[Dict]:
    """
    What agent 3 is missing: forecast demand beyond the signed order book, with
    a date to hang it on.

    Dated at the midpoint of each month's slice of the window. Month start would
    overstate urgency, month end would understate it; the middle is the least
    arguable of the three, and the choice is stated rather than buried.

    Returns [] when no forecast has been run, so agent 3 falls back cleanly to
    the committed book alone.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT period_month, committed_qty, net_demand_qty, drivers->>'_window'
                 FROM platform.demand_forecasts
                WHERE component_id = %s AND horizon_start = %s
                ORDER BY period_month""",
            (component_id, horizon_start),
        )
        rows = cur.fetchall()

    out = []
    for month, committed, net, window in rows:
        gap = net - committed
        if gap <= 0:
            continue
        start_s, end_s = window.split(" to ")
        start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
        out.append({
            "month": month,
            "qty": gap,
            "when": start + timedelta(days=((end - start).days + 1) // 2),
        })
    return out
