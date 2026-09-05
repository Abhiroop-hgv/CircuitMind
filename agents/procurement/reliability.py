"""
Supplier reliability, computed from what actually happened.

A quoted lead time is a promise. This scores the promise against the record:
every closed purchase order has a date the supplier said, and a date the goods
turned up. The gap between those two, over and over, is the score.

Two numbers come out, and they are used in different places:

  score              0..1, recency-weighted on-time rate. Used to adjust the
                     PRICE ranking -- an unreliable supplier is not really the
                     cheapest, it just looks that way on the quote.

  lead_time_padding  days added to a supplier's quoted lead time before we ask
                     "can this arrive in time?". This is where reliability
                     actually bites: a supplier who is habitually nine days
                     late should be treated as nine days slower, and may fail
                     the arrival gate outright.

Recent deliveries count more than old ones, decaying by RECENCY_DECAY per step
back. Same principle as the demand forecaster: what a supplier did last month
tells you more than what they did two years ago.

No model, no learning, no black box. A buyer can reproduce every figure from
the purchase order history in a spreadsheet, which matters when you are telling
a supplier why they lost an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from psycopg.types.json import Jsonb

RECENCY_DECAY = 0.92     # weight of each delivery, one step further back
GRACE_DAYS = 0           # a day late is late
MIN_DELIVERIES = 4       # below this we do not pretend to have a signal
DEFAULT_SCORE = 0.85     # what an unproven supplier is assumed to be


@dataclass
class SupplierScore:
    supplier_id: int
    name: str
    deliveries: int = 0
    on_time: int = 0
    late: int = 0
    on_time_rate: float = DEFAULT_SCORE
    score: float = DEFAULT_SCORE
    avg_days_late: float = 0.0
    worst_days_late: int = 0
    lead_time_padding: int = 0
    history: List[Dict] = field(default_factory=list)
    unproven: bool = False

    def summary(self) -> str:
        if self.unproven:
            return f"no delivery record (assumed {self.score:.2f})"
        return (f"{self.score:.2f} from {self.deliveries} deliveries, "
                f"{self.on_time} on time, {self.late} late"
                + (f", avg {self.avg_days_late:.0f}d over" if self.late else ""))


def compute(conn) -> List[SupplierScore]:
    """Score every supplier from its closed purchase orders."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM erp.suppliers ORDER BY id")
        suppliers = cur.fetchall()

        cur.execute(
            """SELECT supplier_id, po_number, expected_date, actual_receipt_date,
                      (actual_receipt_date - expected_date) AS days_late
                 FROM erp.purchase_orders
                WHERE status = 'RECEIVED' AND actual_receipt_date IS NOT NULL
                ORDER BY supplier_id, actual_receipt_date DESC"""
        )
        rows = cur.fetchall()

    by_supplier: Dict[int, List] = {}
    for supplier_id, po, expected, actual, days_late in rows:
        by_supplier.setdefault(supplier_id, []).append(
            {"po": po, "expected": expected, "actual": actual, "days_late": int(days_late)})

    out = []
    for supplier_id, name in suppliers:
        deliveries = by_supplier.get(supplier_id, [])
        score = SupplierScore(supplier_id=supplier_id, name=name)

        if len(deliveries) < MIN_DELIVERIES:
            score.unproven = True
            score.deliveries = len(deliveries)
            score.history = deliveries[:8]
            out.append(score)
            continue

        weighted_hits = weighted_total = 0.0
        late_days: List[int] = []

        # deliveries are newest first, so index 0 carries the most weight
        for index, d in enumerate(deliveries):
            weight = RECENCY_DECAY ** index
            punctual = d["days_late"] <= GRACE_DAYS
            weighted_total += weight
            if punctual:
                weighted_hits += weight
                score.on_time += 1
            else:
                score.late += 1
                late_days.append(d["days_late"])

        score.deliveries = len(deliveries)
        score.on_time_rate = round(score.on_time / score.deliveries, 3)
        score.score = round(weighted_hits / weighted_total, 3)
        score.avg_days_late = round(sum(late_days) / len(late_days), 2) if late_days else 0.0
        score.worst_days_late = max(late_days) if late_days else 0

        # How many days to add to this supplier's quoted lead time. Expected
        # slip = how often they are late x how late they are when they are.
        score.lead_time_padding = int(round((1 - score.score) * score.avg_days_late))
        score.history = deliveries[:8]
        out.append(score)

    return out


def persist(conn, scores: List[SupplierScore]) -> None:
    with conn.cursor() as cur:
        for s in scores:
            cur.execute(
                """INSERT INTO platform.supplier_scores
                     (supplier_id, deliveries, on_time, late, on_time_rate, score,
                      avg_days_late, worst_days_late, lead_time_padding, history)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (supplier_id) DO UPDATE SET
                     deliveries=EXCLUDED.deliveries, on_time=EXCLUDED.on_time,
                     late=EXCLUDED.late, on_time_rate=EXCLUDED.on_time_rate,
                     score=EXCLUDED.score, avg_days_late=EXCLUDED.avg_days_late,
                     worst_days_late=EXCLUDED.worst_days_late,
                     lead_time_padding=EXCLUDED.lead_time_padding,
                     history=EXCLUDED.history, computed_at=NOW()""",
                (s.supplier_id, s.deliveries, s.on_time, s.late, s.on_time_rate,
                 s.score, s.avg_days_late, s.worst_days_late, s.lead_time_padding,
                 Jsonb([{**h, "expected": str(h["expected"]), "actual": str(h["actual"])}
                        for h in s.history])),
            )
    conn.commit()


def load(conn) -> Dict[int, Dict]:
    """Scores as the Procurement Agent needs them. Empty when never computed."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT supplier_id, score, lead_time_padding, deliveries,
                      on_time, late, avg_days_late
                 FROM platform.supplier_scores"""
        )
        return {
            row[0]: {"score": float(row[1]), "padding": int(row[2]), "deliveries": row[3],
                     "on_time": row[4], "late": row[5], "avg_days_late": float(row[6])}
            for row in cur.fetchall()
        }
