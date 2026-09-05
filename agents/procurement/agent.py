"""
The Procurement Agent.

Input:  4,000 STM32F407VGT6 short, needed by 2026-10-22, plus the alternatives
        agent 4 verified.
Output: a purchase recommendation for a human to approve.

It never places an order. Not in the demo, not anywhere -- the recommendation
stays PENDING_APPROVAL until a person acts on it.

The optimisation is ordinary code. An offer is eligible if it can physically
arrive in time; after that it is price, stock and MOQ. No model is asked what
anything costs, because the answer has to match what the supplier will actually
invoice.

Three questions get answered in order, and the order matters:

  1. Can we cover this WITHOUT touching the BOM? Substituting a fitted part
     means re-qualification and PCB verification. If the original is obtainable
     from suppliers the event did not touch, that is the cheap answer even at a
     higher unit price.
  2. If not, how far does the original get us, and is a part swap unavoidable?
  3. Once we are swapping anyway, buy the whole quantity the best way -- there
     is no partial credit for using some of the old part.

Then, among plans that work: single-source is usually cheapest, and
concentration is exactly what just went wrong. So a dual-source plan is costed
too, and taken when the premium is small.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from psycopg.types.json import Jsonb

from .reliability import load as load_scores

# A split is preferred over a single source when it costs less than this much
# extra. Stated as a number so it can be argued with, rather than buried.
DUAL_SOURCE_PREMIUM_LIMIT = 0.05  # 5%
# How hard an unreliable supplier is penalised when ranking on price. At 0.15
# a supplier who hits their date 55% of the time is costed ~7% above quote.
RISK_PREMIUM = 0.15
MAX_LINES = 3                     # buyers do not want six POs for one part


@dataclass
class Line:
    supplier_id: int
    supplier: str
    country: str
    reliability: float
    score: float
    padding: int
    component_id: int
    mpn: str
    quantity: int
    unit_price: float
    lead_time_days: int
    arrival: date

    @property
    def total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


@dataclass
class Plan:
    name: str
    lines: List[Line] = field(default_factory=list)
    shortfall: int = 0          # quantity it could not cover
    requires_bom_change: bool = False

    @property
    def total_cost(self) -> float:
        return round(sum(l.total for l in self.lines), 2)

    @property
    def latest_arrival(self) -> Optional[date]:
        return max((l.arrival for l in self.lines), default=None)

    @property
    def viable(self) -> bool:
        return self.shortfall == 0 and bool(self.lines)

    @property
    def suppliers(self) -> int:
        return len({l.supplier_id for l in self.lines})


class ProcurementAgent:
    def __init__(self, conn, today: Optional[date] = None):
        self.conn = conn
        self.today = today or date(2026, 9, 3)
        # Empty until reliability has been computed; every offer then falls
        # back to its quoted lead time and quoted price, unadjusted.
        self.scores = load_scores(conn)

    # -- offers ------------------------------------------------------------

    def _offers(self, component_id: int, need_by: date,
                exclude_suppliers: List[int]) -> List[Dict]:
        """
        Every way to buy this part that can physically land in time.

        Suppliers the event hit are excluded outright -- buying from the lane
        that just closed is not a recovery plan.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT sc.supplier_id, s.name, s.country, s.reliability_score,
                          sc.unit_price, sc.lead_time_days, sc.moq, sc.stock_available,
                          c.mpn
                     FROM erp.supplier_components sc
                     JOIN erp.suppliers s  ON s.id = sc.supplier_id
                     JOIN erp.components c ON c.id = sc.component_id
                    WHERE sc.component_id = %s
                      AND sc.stock_available > 0
                      AND s.is_approved
                      AND NOT (sc.supplier_id = ANY(%s))
                    ORDER BY sc.unit_price""",
                (component_id, exclude_suppliers),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        out = []
        for r in rows:
            # What this supplier's promise is worth, given what they actually do.
            record = self.scores.get(r["supplier_id"], {"score": 1.0, "padding": 0})
            r["score"] = record["score"]
            r["padding"] = record["padding"]
            r["effective_lead"] = int(r["lead_time_days"]) + record["padding"]

            # An unreliable supplier is not really the cheapest -- it only looks
            # that way on the quote. Rank on a price that says so.
            r["adjusted_price"] = round(
                float(r["unit_price"]) * (1 + (1 - record["score"]) * RISK_PREMIUM), 4)

            arrival = self.today + timedelta(days=r["effective_lead"])
            if arrival <= need_by:
                r["component_id"] = component_id
                r["arrival"] = arrival
                out.append(r)
        return out

    # -- plan builders -----------------------------------------------------

    def _allocate(self, offers: List[Dict], qty: int, name: str,
                  max_share: float = 1.0) -> Plan:
        """
        Greedy fill over offers in whatever order they arrive in.

        max_share caps how much of the requirement one supplier may take, which
        is how the dual-source plan is built without a second algorithm.
        """
        plan = Plan(name=name)
        remaining = qty
        cap = int(qty * max_share)

        for o in offers:
            if remaining <= 0 or len(plan.lines) >= MAX_LINES:
                break
            take = min(remaining, int(o["stock_available"]), cap)
            if take < int(o["moq"] or 1):
                continue
            plan.lines.append(Line(
                supplier_id=o["supplier_id"], supplier=o["name"], country=o["country"],
                reliability=float(o["reliability_score"]),
                score=o.get("score", 1.0), padding=o.get("padding", 0),
                component_id=o["component_id"], mpn=o["mpn"], quantity=take,
                unit_price=float(o["unit_price"]),
                lead_time_days=int(o["lead_time_days"]), arrival=o["arrival"],
            ))
            remaining -= take

        plan.shortfall = max(0, remaining)
        return plan

    # -- the decision ------------------------------------------------------

    def recommend(self, component_id: int, mpn: str, qty: int, need_by: date,
                  alternatives: List[Dict], affected_suppliers: List[int]) -> Dict:
        considered: List[Dict] = []

        # 1. can we avoid a BOM change entirely?
        original_offers = self._offers(component_id, need_by, affected_suppliers)
        keep_bom = self._allocate(sorted(original_offers, key=lambda o: o["adjusted_price"]),
                                  qty, "original part, no BOM change")
        considered.append(_summarise(keep_bom))

        if keep_bom.viable:
            return _result(keep_bom, considered,
                           "The original part is obtainable in full from suppliers the event "
                           "does not touch. No engineering change needed.")

        covered = qty - keep_bom.shortfall

        # 2. a swap is unavoidable. Once we are swapping, swap the whole
        #    quantity -- there is no partial credit for using some of the old
        #    part, and mixing two part numbers on one build is worse, not better.
        best: Optional[Plan] = None
        best_alt = None
        for alt in alternatives:
            offers = self._offers(alt["component_id"], need_by, affected_suppliers)
            if not offers:
                continue
            cheapest = self._allocate(sorted(offers, key=lambda o: o["adjusted_price"]),
                                      qty, f"switch to {alt['mpn']}, lowest cost")
            cheapest.requires_bom_change = True
            considered.append(_summarise(cheapest))
            if cheapest.viable and (best is None or cheapest.total_cost < best.total_cost):
                best, best_alt = cheapest, (alt, offers)

        if best is None:
            return _result(keep_bom, considered,
                           f"No single source covers {qty:,} units by {need_by}. "
                           f"The original part covers only {covered:,}. "
                           f"This needs a buyer, not an automated recommendation.")

        alt, offers = best_alt

        # 3. single source is cheapest, and concentration is what just bit us.
        #    Cost the split and take it when the premium is small.
        dual = self._allocate(sorted(offers, key=lambda o: o["adjusted_price"]),
                              qty, f"switch to {alt['mpn']}, dual sourced", max_share=0.6)
        dual.requires_bom_change = True

        if dual.viable and dual.suppliers > best.suppliers:
            considered.append(_summarise(dual))
            premium = (dual.total_cost - best.total_cost) / best.total_cost
            if premium <= DUAL_SOURCE_PREMIUM_LIMIT:
                return _result(
                    dual, considered,
                    f"The original part covers only {covered:,} of {qty:,} from unaffected "
                    f"suppliers, so a substitution is unavoidable. {alt['mpn']} is verified "
                    f"against every board that fits the original. Split across "
                    f"{dual.suppliers} suppliers for "
                    f"{premium * 100:.1f}% more than single sourcing -- concentration is "
                    f"what caused this shortage in the first place.")

        # Describe the plan we actually chose. The cheapest option is not always
        # single-sourced -- when no one supplier holds enough stock it spans
        # several by necessity, and calling that "single sourcing" out loud in
        # front of a buyer would be plainly wrong.
        if best.suppliers == 1:
            shape = ("a single supplier holds the whole quantity, and splitting it would "
                     "cost more without reducing exposure")
        else:
            deepest = max(best.lines, key=lambda l: l.quantity)
            share = deepest.quantity / qty
            shape = (f"no single supplier holds {qty:,}, so it spans {best.suppliers} of them "
                     f"already, with {deepest.supplier[:26]} carrying {share * 100:.0f}%")

        return _result(
            best, considered,
            f"The original part covers only {covered:,} of {qty:,} from unaffected suppliers, "
            f"so a substitution is unavoidable. {alt['mpn']} is verified against every board "
            f"that fits the original. On cost, {shape}.")

    # -- persistence -------------------------------------------------------

    def persist(self, event_id: Optional[int], component_id: int,
                qty: int, need_by: date, result: Dict) -> int:
        plan: Plan = result["plan"]
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM platform.purchase_recommendations "
                "WHERE event_id IS NOT DISTINCT FROM %s AND original_component_id = %s "
                "AND status = 'PENDING_APPROVAL'",
                (event_id, component_id),
            )
            cur.execute(
                """INSERT INTO platform.purchase_recommendations
                     (event_id, original_component_id, qty_required, need_by, strategy,
                      rationale, requires_bom_change, total_cost, latest_arrival, considered)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (event_id, component_id, qty, need_by, plan.name, result["rationale"],
                 plan.requires_bom_change, plan.total_cost,
                 plan.latest_arrival or need_by, Jsonb(result["considered"])),
            )
            reco_id = cur.fetchone()[0]

            for l in plan.lines:
                cur.execute(
                    """INSERT INTO platform.purchase_recommendation_lines
                         (recommendation_id, supplier_id, component_id, quantity,
                          unit_price, line_total, lead_time_days, expected_arrival,
                          supplier_reliability)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (reco_id, l.supplier_id, l.component_id, l.quantity, l.unit_price,
                     l.total, l.lead_time_days, l.arrival, l.reliability),
                )
        self.conn.commit()
        return reco_id


def approve(conn, reco_id: int, who: str) -> bool:
    """
    The human gate. This marks a recommendation approved and does NOTHING else --
    it does not contact a supplier, and there is no code path in this project
    that does.
    """
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE platform.purchase_recommendations
                  SET status = 'APPROVED', approved_by = %s, approved_at = NOW()
                WHERE id = %s AND status = 'PENDING_APPROVAL'""",
            (who, reco_id),
        )
        changed = cur.rowcount
    conn.commit()
    return changed == 1


def _summarise(plan: Plan) -> Dict:
    return {
        "plan": plan.name,
        "viable": plan.viable,
        "shortfall": plan.shortfall,
        "suppliers": plan.suppliers,
        "total_cost": plan.total_cost,
        "latest_arrival": str(plan.latest_arrival) if plan.latest_arrival else None,
    }


def _result(plan: Plan, considered: List[Dict], rationale: str) -> Dict:
    return {"plan": plan, "considered": considered, "rationale": rationale}
