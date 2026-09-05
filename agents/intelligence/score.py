"""
Step 3 of the Intelligence Agent: how exposed are we?

No language model, no ML. A small rule table you can read out loud on stage and
defend, with every input it used recorded alongside the verdict.

This step deliberately stops short of computing a shortage. Whether we actually
run out depends on demand, stock, safety stock and every other open PO -- that
is the Supply Risk Agent's arithmetic, and duplicating it here would give us two
numbers that drift apart. What this answers is narrower: how concentrated is our
exposure, and is there another way to get the part?
"""

from __future__ import annotations

from typing import Dict, Tuple

from .match import ComponentMatch

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"


def score(conn, m: ComponentMatch) -> Tuple[str, Dict]:
    """Return (risk_level, rule_inputs) for one affected component."""

    with conn.cursor() as cur:
        # What could we get from suppliers the event does NOT touch?
        cur.execute(
            """SELECT COALESCE(SUM(sc.stock_available), 0)::int,
                      COUNT(*)::int
                 FROM erp.supplier_components sc
                WHERE sc.component_id = %s
                  AND NOT (sc.supplier_id = ANY(%s))""",
            (m.component_id, m.supplier_ids),
        )
        unaffected_stock, unaffected_supplier_count = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(sc.stock_available), 0)::int
                 FROM erp.supplier_components sc
                WHERE sc.component_id = %s AND sc.supplier_id = ANY(%s)""",
            (m.component_id, m.supplier_ids),
        )
        affected_stock = cur.fetchone()[0]

    total_stock = affected_stock + unaffected_stock
    concentration = round(affected_stock / total_stock, 3) if total_stock else 0.0
    covers_at_risk = unaffected_stock >= m.at_risk_qty

    # For a part made in the affected place, the question is not what is in
    # transit -- that is already built and on a ship. It is whether we can get
    # MORE of it, and whether anything in the catalogue comes from elsewhere.
    other_origins = 0
    if m.hits_origin:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*)::int FROM erp.components
                    WHERE category = %s AND lifecycle = 'ACTIVE'
                      AND COALESCE(country_of_origin, '') <> %s""",
                (m.category, m.origin_country),
            )
            other_origins = cur.fetchone()[0]

    rule_inputs = {
        "match_basis": m.basis,
        "origin_country": m.origin_country,
        "in_use_on_a_board": bool(m.product_ids),
        "is_critical": m.is_critical,
        "at_risk_qty": m.at_risk_qty,
        "affected_supplier_stock": affected_stock,
        "unaffected_supplier_stock": unaffected_stock,
        "unaffected_supplier_count": unaffected_supplier_count,
        "sourcing_concentration_on_affected": concentration,
        "unaffected_stock_covers_at_risk_qty": covers_at_risk,
        "same_category_parts_from_elsewhere": other_origins,
    }

    # ---- the rule table -----------------------------------------------------
    if not m.product_ids:
        # We can buy it, but no board currently fits it. Worth knowing when we
        # go looking for a substitute; not a risk to today's production.
        return LOW, {**rule_inputs, "rule": "not fitted on any current board"}

    if m.hits_origin and m.at_risk_qty == 0:
        # Made in the affected place, nothing of ours in that shipping lane.
        # Shelf stock is unaffected; replenishment is the exposure.
        if other_origins == 0:
            return HIGH, {**rule_inputs,
                          "rule": "made there, and we catalogue no part in this "
                                  "category from anywhere else"}
        return MEDIUM, {**rule_inputs,
                        "rule": f"made there -- replenishment at risk, but "
                                f"{other_origins} catalogued part(s) in this category "
                                f"come from elsewhere"}

    if m.at_risk_qty == 0:
        # Exposed supplier, but nothing of ours is in flight from there.
        return LOW, {**rule_inputs, "rule": "no open purchase order in the affected lane"}

    if m.is_critical and not covers_at_risk:
        return HIGH, {**rule_inputs, "rule": "critical part, in flight, no unaffected source deep enough"}

    if m.is_critical or not covers_at_risk:
        return MEDIUM, {**rule_inputs, "rule": "either critical or thinly covered elsewhere, but not both"}

    return LOW, {**rule_inputs, "rule": "in flight, but comfortably sourceable elsewhere"}
