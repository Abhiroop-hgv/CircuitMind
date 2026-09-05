"""
The Component Intelligence Agent.

Takes "we are 4,000 STM32F407VGT6 short by 22 October" and finds a part that can
actually go on the board.

Two stages, and keeping them apart is the point:

  RETRIEVE   narrow 30,000 parts down to a handful worth checking. Cheap, fuzzy,
             allowed to be wrong -- a bad candidate here costs nothing because
             the next stage throws it out.
  VERIFY     decide. Deterministic rules against bom.design_constraints. This
             stage is never allowed to be fuzzy, because its output goes on a
             board.

Retrieval today is a SQL filter on category. With a 30-part catalogue that IS
the retrieval -- pgvector would be theatre at this scale, and it is not even
installed on this machine. The interface is deliberately narrow so a vector
implementation drops in unchanged when the catalogue is large enough to need
one: same signature, same return, and the verification stage does not care
where the candidates came from.

A part used on several boards must satisfy EVERY board that uses it. The
STM32F407VGT6 is on the MC-3000 and the SD-220, and their requirements differ,
so a candidate that only clears the looser one is not a replacement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from psycopg.types.json import Jsonb

from .rules import Check, evaluate, failures, score, verdict


@dataclass
class BoardVerdict:
    product_id: int
    sku: str
    verdict: str
    score: int
    checks: List[Check]


@dataclass
class Candidate:
    component_id: int
    mpn: str
    manufacturer: str
    standard_cost: float
    country_of_origin: str
    boards: List[BoardVerdict] = field(default_factory=list)
    sourcing_note: str = ""
    unaffected_suppliers: int = 0
    unaffected_stock: int = 0

    @property
    def sourcing_risk(self) -> bool:
        """No supplier outside the blast radius sells this part."""
        return self.unaffected_suppliers == 0

    @property
    def verdict(self) -> str:
        return "PASS" if self.boards and all(b.verdict == "PASS" for b in self.boards) else "FAIL"

    @property
    def score(self) -> int:
        return min(b.score for b in self.boards) if self.boards else 0

    @property
    def first_failure(self) -> Optional[Check]:
        for b in self.boards:
            bad = failures(b.checks)
            if bad:
                return bad[0]
        return None


class ComponentAgent:
    def __init__(self, conn):
        self.conn = conn

    # -- stage 1: retrieve --------------------------------------------------

    def retrieve(self, component_id: int, limit: int = 12) -> List[Dict]:
        """
        Candidates worth checking. Same category, still in production, not the
        part we are replacing. Deliberately generous -- verification is what
        narrows it, and a candidate that fails costs one dictionary lookup.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT c.id, c.mpn, c.manufacturer, c.standard_cost,
                          c.country_of_origin, c.specs
                     FROM erp.components c
                    WHERE c.category = (SELECT category FROM erp.components WHERE id = %s)
                      AND c.id <> %s
                      AND c.lifecycle = 'ACTIVE'
                    ORDER BY c.standard_cost
                    LIMIT %s""",
                (component_id, component_id, limit),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    # -- stage 2: verify ----------------------------------------------------

    def _requirements(self, component_id: int) -> List[Dict]:
        """Every board that fits this part, and what each of them demands."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT p.id, p.sku, b.design_constraints
                     FROM erp.bom b
                     JOIN erp.products p ON p.id = b.product_id
                    WHERE b.component_id = %s
                    ORDER BY p.sku""",
                (component_id,),
            )
            return [{"product_id": r[0], "sku": r[1], "constraints": r[2]}
                    for r in cur.fetchall()]

    def _sourcing(self, candidate_id: int, affected_supplier_ids: List[int]) -> tuple:
        """
        Technically valid is not the same as obtainable. A part sourced only
        from the suppliers the event just hit is not an escape route.

        Returns (suppliers, stock) outside the blast radius.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FILTER (WHERE NOT (supplier_id = ANY(%s))),
                          COALESCE(SUM(stock_available) FILTER
                                   (WHERE NOT (supplier_id = ANY(%s))), 0)::int
                     FROM erp.supplier_components WHERE component_id = %s""",
                (affected_supplier_ids, affected_supplier_ids, candidate_id),
            )
            suppliers, stock = cur.fetchone()
        return int(suppliers or 0), int(stock or 0)

    def assess(self, component_id: int, affected_supplier_ids: List[int] = None,
               extra_constraints: Dict = None) -> List[Candidate]:
        """
        Candidates, checked against every board that carries the part.

        `extra_constraints` are the non-negotiables an engineer set for this run.
        They are merged on top of each board's own design constraints and take
        precedence, because a person who has just typed "this must run at 3.3 V"
        knows something the stored BOM does not. They are enforced by the same
        rule engine as everything else rather than by a special case, so a
        candidate that fails one fails visibly, with the reason named.
        """
        affected_supplier_ids = affected_supplier_ids or []
        extra_constraints = extra_constraints or {}
        requirements = self._requirements(component_id)

        if extra_constraints:
            for req in requirements:
                req["constraints"] = {**req["constraints"], **extra_constraints}
            # A part on no board yet -- a new BOM line -- still has to satisfy
            # what the engineer asked for, so give it something to be judged by.
            if not requirements:
                requirements = [{"product_id": None, "sku": "this run",
                                 "constraints": dict(extra_constraints)}]
        out = []

        for row in self.retrieve(component_id):
            candidate = Candidate(
                component_id=row["id"],
                mpn=row["mpn"],
                manufacturer=row["manufacturer"],
                standard_cost=float(row["standard_cost"] or 0),
                country_of_origin=row["country_of_origin"] or "",
            )
            # Manufacturer and origin live in columns rather than in the specs
            # blob, so the rule engine cannot see them. An engineer setting a
            # non-negotiable is as likely to say "STMicroelectronics only" or
            # "nothing fabbed in China" as to name an electrical limit, so put
            # them where a constraint can reach them.
            spec = {**(row["specs"] or {}),
                    "manufacturer": row["manufacturer"],
                    "country_of_origin": row["country_of_origin"] or ""}

            for req in requirements:
                checks = evaluate(spec, req["constraints"])
                candidate.boards.append(BoardVerdict(
                    product_id=req["product_id"], sku=req["sku"],
                    verdict=verdict(checks), score=score(checks), checks=checks,
                ))
            suppliers, stock = self._sourcing(row["id"], affected_supplier_ids)
            candidate.unaffected_suppliers = suppliers
            candidate.unaffected_stock = stock
            candidate.sourcing_note = (
                "SOURCING RISK: only available from suppliers this event affects"
                if suppliers == 0
                else f"{stock:,} units across {suppliers} unaffected supplier(s)"
            )
            out.append(candidate)

        # Ranking order, and why:
        #   1. does it fit at all
        #   2. can we get it from outside the blast radius -- a part sourced only
        #      from the suppliers this event just hit is not an escape route, and
        #      leading a buyer with one would be misleading even with a warning
        #      printed beside it. It stays on the list; it does not stay on top.
        #   3. best technical fit
        #   4. cheapest
        out.sort(key=lambda c: (c.verdict != "PASS", c.sourcing_risk,
                                -c.score, c.standard_cost))
        return out

    # -- persistence --------------------------------------------------------

    def persist(self, event_id: Optional[int], original_id: int,
                candidates: List[Candidate]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM platform.alternatives WHERE event_id IS NOT DISTINCT FROM %s "
                "AND original_component_id = %s",
                (event_id, original_id),
            )
            for rank, c in enumerate(candidates, start=1):
                cur.execute(
                    """INSERT INTO platform.alternatives
                         (event_id, original_component_id, candidate_component_id,
                          verdict, compatibility_score, rank, sourcing_note, checks)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (event_id, original_id, c.component_id, c.verdict, c.score, rank,
                     c.sourcing_note,
                     Jsonb([{
                         "board": b.sku,
                         "verdict": b.verdict,
                         "score": b.score,
                         "checks": [{"name": k.name, "required": k.required,
                                     "actual": k.actual, "ok": k.ok} for k in b.checks],
                     } for b in c.boards])),
                )
        self.conn.commit()


def handoff_to_procurement(conn, original_component_id: int) -> List[Dict]:
    """What agent 5 picks up: the parts it is allowed to buy."""
    with conn.cursor() as cur:
        # DISTINCT ON keeps the newest assessment per candidate. The same
        # candidate can be assessed more than once -- by a news event and by a
        # build request -- and the two runs see different affected suppliers, so
        # their sourcing notes legitimately differ. The latest one is the truth.
        cur.execute(
            """SELECT component_id, mpn, compatibility_score, sourcing_note FROM (
                   SELECT DISTINCT ON (a.candidate_component_id)
                          c.id AS component_id, c.mpn, a.compatibility_score,
                          a.sourcing_note, a.rank
                     FROM platform.alternatives a
                     JOIN erp.components c ON c.id = a.candidate_component_id
                    WHERE a.original_component_id = %s AND a.verdict = 'PASS'
                    ORDER BY a.candidate_component_id, a.created_at DESC
               ) latest ORDER BY rank""",
            (original_component_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
