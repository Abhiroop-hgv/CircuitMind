"""
Step 2 of the Intelligence Agent: structured reading -> our entities.

No language model runs here. This is the step that decides whether an event
touches this company, and it is deliberately made of joins so that every claim
the system makes downstream traces back to a row someone can look at.

The narrowing that matters happens in one place: an event only reaches a
component if the supplier geography matches AND the component's category is one
the article actually named. Geography alone would flag half the parts bin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List

from .schema import EventExtraction


SUPPLIER_LANE = "SUPPLIER_LANE"
PART_ORIGIN = "PART_ORIGIN"
BOTH = "BOTH"


@dataclass
class ComponentMatch:
    component_id: int
    mpn: str
    category: str
    supplier_ids: List[int] = field(default_factory=list)
    supplier_names: List[str] = field(default_factory=list)
    product_ids: List[int] = field(default_factory=list)
    product_skus: List[str] = field(default_factory=list)
    is_critical: bool = False
    at_risk_po_ids: List[int] = field(default_factory=list)
    at_risk_qty: int = 0
    basis: str = SUPPLIER_LANE
    origin_country: str = ""

    @property
    def hits_origin(self) -> bool:
        return self.basis in (PART_ORIGIN, BOTH)

    @property
    def hits_lane(self) -> bool:
        return self.basis in (SUPPLIER_LANE, BOTH)


@dataclass
class MatchResult:
    supplier_ids: List[int] = field(default_factory=list)
    supplier_names: List[str] = field(default_factory=list)
    components: List[ComponentMatch] = field(default_factory=list)
    skipped_reason: str = ""


def component_categories(conn) -> List[str]:
    """The controlled vocabulary the extractor is held to."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT category FROM erp.components ORDER BY category")
        return [r[0] for r in cur.fetchall()]


def match(conn, extraction: EventExtraction, horizon_end: date) -> MatchResult:
    if not extraction.affects_physical_supply:
        return MatchResult(skipped_reason="not a physical supply event")

    with conn.cursor() as cur:
        # --- who does this reach? geography, or a supplier named outright -----
        cur.execute(
            """SELECT id, name
                 FROM erp.suppliers
                WHERE country = ANY(%(countries)s)
                   OR city    = ANY(%(cities)s)
                   OR EXISTS (SELECT 1 FROM unnest(%(orgs)s::text[]) o
                               WHERE erp.suppliers.name ILIKE '%%' || o || '%%')
                ORDER BY name""",
            {
                "countries": extraction.countries,
                "cities": extraction.cities,
                "orgs": extraction.named_organisations,
            },
        )
        suppliers = cur.fetchall()
        supplier_ids = [s[0] for s in suppliers]
        supplier_names = [s[1] for s in suppliers]

        # --- what is the article actually about? ------------------------------
        # An empty category list means the article named no category we stock.
        # We do NOT fall back to "everything they sell" -- that is how a port
        # closure ends up flagging every resistor on the board.
        if not extraction.component_categories:
            return MatchResult(
                supplier_ids=supplier_ids,
                supplier_names=supplier_names,
                skipped_reason="no component category of ours was named",
            )

        by_id: Dict[int, ComponentMatch] = {}
        name_of = dict(zip(supplier_ids, supplier_names))

        # --- path 1: our supplier is IN the affected place --------------------
        # Their shipments to us are at risk. Goods in transit are the exposure.
        if supplier_ids:
            cur.execute(
                """SELECT c.id, c.mpn, c.category, c.country_of_origin,
                          array_agg(DISTINCT sc.supplier_id) AS supplier_ids
                     FROM erp.supplier_components sc
                     JOIN erp.components c ON c.id = sc.component_id
                    WHERE sc.supplier_id = ANY(%(suppliers)s)
                      AND c.category     = ANY(%(categories)s)
                    GROUP BY c.id, c.mpn, c.category, c.country_of_origin
                    ORDER BY c.mpn""",
                {"suppliers": supplier_ids, "categories": extraction.component_categories},
            )
            for component_id, mpn, category, origin, sup_ids in cur.fetchall():
                by_id[component_id] = ComponentMatch(
                    component_id=component_id, mpn=mpn, category=category,
                    supplier_ids=sorted(sup_ids),
                    supplier_names=[name_of[s] for s in sorted(sup_ids)],
                    basis=SUPPLIER_LANE, origin_country=origin or "",
                )

        # --- path 2: the part is MADE in the affected place -------------------
        # Whoever sells it to us. A fab fire in Japan reaches a Murata capacitor
        # bought through a US distributor, because buying through a distributor
        # does not move the fab. Missing this was a real gap: an event with no
        # supplier of ours in the country produced nothing at all, however much
        # of our bill of materials was made there.
        cur.execute(
            """SELECT c.id, c.mpn, c.category, c.country_of_origin
                 FROM erp.components c
                WHERE c.category          = ANY(%(categories)s)
                  AND c.country_of_origin = ANY(%(countries)s)
                ORDER BY c.mpn""",
            {"categories": extraction.component_categories,
             "countries": extraction.countries},
        )
        for component_id, mpn, category, origin in cur.fetchall():
            existing = by_id.get(component_id)
            if existing:
                existing.basis = BOTH
                existing.origin_country = origin or ""
                continue
            by_id[component_id] = ComponentMatch(
                component_id=component_id, mpn=mpn, category=category,
                basis=PART_ORIGIN, origin_country=origin or "",
            )

        if not by_id:
            reason = ("affected suppliers do not sell us that category, and we fit "
                      "nothing made there" if supplier_ids
                      else "no supplier of ours there, and we fit nothing made there")
            return MatchResult(supplier_ids=supplier_ids, supplier_names=supplier_names,
                               skipped_reason=reason)

        ids = list(by_id)

        # --- which of our boards use them? ------------------------------------
        cur.execute(
            """SELECT b.component_id, p.id, p.sku, bool_or(b.is_critical)
                 FROM erp.bom b
                 JOIN erp.products p ON p.id = b.product_id
                WHERE b.component_id = ANY(%s)
                GROUP BY b.component_id, p.id, p.sku
                ORDER BY p.sku""",
            (ids,),
        )
        for component_id, product_id, sku, critical in cur.fetchall():
            m = by_id[component_id]
            m.product_ids.append(product_id)
            m.product_skus.append(sku)
            m.is_critical = m.is_critical or critical

        # --- what is already in flight from the affected place? ---------------
        cur.execute(
            """SELECT i.component_id, po.id, SUM(i.quantity - i.received_qty)::int
                 FROM erp.purchase_order_items i
                 JOIN erp.purchase_orders po ON po.id = i.po_id
                WHERE i.component_id = ANY(%(components)s)
                  AND po.status IN ('OPEN', 'PARTIAL')
                  AND po.expected_date <= %(horizon_end)s
                  AND (po.supplier_id = ANY(%(suppliers)s)
                       OR po.ship_from_country = ANY(%(countries)s))
                GROUP BY i.component_id, po.id""",
            {
                "components": ids,
                "suppliers": supplier_ids,
                "countries": extraction.countries,
                "horizon_end": horizon_end,
            },
        )
        for component_id, po_id, qty in cur.fetchall():
            m = by_id[component_id]
            m.at_risk_po_ids.append(po_id)
            m.at_risk_qty += qty

    return MatchResult(
        supplier_ids=supplier_ids,
        supplier_names=supplier_names,
        components=sorted(by_id.values(), key=lambda m: m.mpn),
    )
