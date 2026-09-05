"""
Can we actually build this board?

Takes a registered build request -- "500 x SH-100 by 15 November" -- and answers
it against everything already committed. Writes `platform.shortages`, which is
the same table the Supply Risk Agent writes, so agents 4 and 5 pick the result up
without a line of change.

THE QUESTION IS INCREMENTAL, NOT ISOLATED
-----------------------------------------
The tempting version is "do we have enough parts for 500 boards?" -- stock
against BOM. It is also wrong, and flatteringly so. The STM32F407VGT6 on this new
board is the same part already promised to MC-3000 and SD-220 customers. Asking
in isolation counts that stock twice and reports a build as feasible while
quietly planning to consume parts someone else's order needs.

So the real question is: **on top of everything already committed, can we also
build this?** The ledger already carries existing demand; the new board's
requirement is added to it.

That also makes the baseline meaningful. Running the same ledger without the new
build separates two very different findings:

    baseline 0, with build 4,000    the new board causes the shortage
    baseline 4,000, with build 4,000 you were already short; the board is innocent

WHEN THE PARTS ARE NEEDED
-------------------------
Dated at the need-by date, not spread across the horizon. A build is a single
event: 500 boards on 15 November needs all 500 sets of parts before then. Real
planning would work back through assembly lead time and kitting; we do not have
those figures and will not invent them, so need-by is the honest simplification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from psycopg.types.json import Jsonb

from agents.supply_risk.agent import Movement, Shortage, SupplyRiskAgent


@dataclass
class BuildLine:
    component_id: int
    mpn: str
    qty_per_board: int
    required: int
    shortage: Shortage


@dataclass
class BuildAssessment:
    request_id: int
    sku: str
    name: str
    build_qty: int
    need_by: date
    lines: List[BuildLine]
    unknown_mpns: List[str]

    @property
    def blocked_by(self) -> List[BuildLine]:
        return [l for l in self.lines if l.shortage.shortage_qty > 0]

    @property
    def buildable(self) -> bool:
        return not self.blocked_by and not self.unknown_mpns


class BuildabilityAgent:
    def __init__(self, conn, today: Optional[date] = None):
        self.conn = conn
        self.today = today or date(2026, 9, 3)

    def _request(self, request_id: int) -> Dict:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id, product_id, product_sku, product_name, build_qty,
                          need_by, status
                     FROM platform.build_requests WHERE id = %s""",
                (request_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"no build request {request_id}")
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def _bom(self, product_id: int) -> List[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT b.component_id, c.mpn, b.qty_per_unit::int
                     FROM erp.bom b
                     JOIN erp.components c ON c.id = b.component_id
                    WHERE b.product_id = %s
                    ORDER BY c.mpn""",
                (product_id,),
            )
            return cur.fetchall()

    def _unknown(self, request_id: int) -> List[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT mpn_raw FROM platform.build_request_lines
                    WHERE request_id = %s AND resolution = 'UNKNOWN'
                    ORDER BY line_number""",
                (request_id,),
            )
            return [r[0] for r in cur.fetchall()]

    # -- the calculation ---------------------------------------------------

    def assess(self, request_id: int) -> BuildAssessment:
        req = self._request(request_id)
        if req["product_id"] is None:
            raise ValueError("build request is not registered as a product yet")

        need_by = req["need_by"]
        # Same ledger as agent 3, run to this build's own need-by date.
        risk = SupplyRiskAgent(self.conn, today=self.today, horizon_end=need_by)

        lines: List[BuildLine] = []
        for component_id, mpn, qty_per_board in self._bom(req["product_id"]):
            required = qty_per_board * req["build_qty"]

            committed = risk.demand_movements(component_id)
            arrivals = risk.arrival_movements(component_id, [], None)
            opening = risk.usable_stock(component_id)

            build_demand = [Movement(
                when=need_by, qty=-required, kind="BUILD",
                ref=req["product_sku"],
                note=f"{req['build_qty']:,} boards x {qty_per_board} per board",
            )]

            with_build, first_short, ledger = risk.walk(
                opening, committed + arrivals + build_demand)
            without_build, _, _ = risk.walk(opening, committed + arrivals)

            shortage = Shortage(
                component_id=component_id, mpn=mpn,
                horizon_start=self.today, horizon_end=need_by,
                demand_qty=-sum(m.qty for m in committed) + required,
                usable_stock=opening,
                incoming_on_time=sum(m.qty for m in arrivals if m.when <= need_by),
                shortage_qty=with_build,
                first_shortfall_date=first_short,
                baseline_shortage_qty=without_build,
                ledger=ledger,
            )
            shortage.severity = SupplyRiskAgent._severity(shortage)

            lines.append(BuildLine(component_id, mpn, qty_per_board, required, shortage))

        return BuildAssessment(
            request_id=request_id, sku=req["product_sku"], name=req["product_name"],
            build_qty=req["build_qty"], need_by=need_by, lines=lines,
            unknown_mpns=self._unknown(request_id),
        )

    # -- handoff -----------------------------------------------------------

    def persist(self, assessment: BuildAssessment) -> int:
        """
        Write shortages so agents 4 and 5 can act. Only the lines that are
        actually short: a build request touching 14 components should not put 14
        rows in front of a buyer when 13 of them are fine.
        """
        written = 0
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM platform.shortages WHERE build_request_id = %s",
                        (assessment.request_id,))
            for line in assessment.blocked_by:
                s = line.shortage
                cur.execute(
                    """INSERT INTO platform.shortages
                         (build_request_id, component_id, horizon_start, horizon_end,
                          demand_qty, usable_stock, incoming_on_time, incoming_delayed,
                          incoming_lost, expected_supply, shortage_qty,
                          first_shortfall_date, severity, baseline_shortage_qty, ledger)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (assessment.request_id, s.component_id, s.horizon_start,
                     s.horizon_end, s.demand_qty, s.usable_stock, s.incoming_on_time,
                     0, 0, s.expected_supply, s.shortage_qty, s.first_shortfall_date,
                     s.severity, s.baseline_shortage_qty, Jsonb(s.ledger)),
                )
                written += 1
        self.conn.commit()
        return written
