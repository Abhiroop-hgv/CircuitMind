"""
Recommendations: the list, one in full, approving one, and the purchase orders that follow.
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from agents.procurement.agent import approve
from api.serialization import rows
from db.connection import connect, pooled

router = APIRouter()

@router.get("/api/recommendations")
def recommendations() -> List[Dict]:
    with pooled() as conn, conn.cursor() as cur:
        cur.execute("""SELECT r.id, c.mpn AS original_mpn, c.category, c.description,
                              r.qty_required, r.need_by,
                              r.strategy, r.rationale, r.requires_bom_change,
                              r.total_cost, r.latest_arrival, r.status,
                              r.approved_by, r.considered,
                              -- the event that caused this, so the list can say
                              -- WHY a recommendation exists without a click
                              e.headline AS event_headline,
                              e.extracted->>'event_type' AS event_type,
                              (SELECT json_agg(json_build_object(
                                   'supplier', s.name, 'mpn', lc.mpn,
                                   'quantity', l.quantity, 'unit_price', l.unit_price,
                                   'line_total', l.line_total,
                                   'arrival', l.expected_arrival,
                                   'reliability', l.supplier_reliability))
                                 FROM platform.purchase_recommendation_lines l
                                 JOIN erp.suppliers s   ON s.id = l.supplier_id
                                 JOIN erp.components lc ON lc.id = l.component_id
                                WHERE l.recommendation_id = r.id) AS lines
                         FROM platform.purchase_recommendations r
                         JOIN erp.components c ON c.id = r.original_component_id
                         -- LEFT: a recommendation raised by a new BOM has no event
                         LEFT JOIN platform.external_events e ON e.id = r.event_id
                        ORDER BY r.id DESC""")
        return rows(cur)


@router.get("/api/recommendations/{reco_id}/po/manifest")
def purchase_order_manifest(reco_id: int) -> Dict:
    """The orders this recommendation would produce, without producing them."""
    from agents.procurement.po import NotApproved, summary

    conn = connect()
    try:
        return summary(conn, reco_id)
    except NotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        conn.close()


@router.get("/api/recommendations/{reco_id}/po.zip")
def purchase_orders_zip(reco_id: int):
    """One PDF per supplier, zipped. This is the set a buyer sends out."""
    from agents.procurement.po import NotApproved, build_zip

    conn = connect()
    try:
        blob = build_zip(conn, reco_id)
    except NotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        conn.close()

    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="PO-{reco_id}.zip"'},
    )


@router.get("/api/recommendations/{reco_id}/po")
def purchase_orders(reco_id: int, supplier: str = ""):
    """
    The purchase orders for an approved recommendation, as a PDF.

    One order per supplier, because that is what a purchase order is. Refused
    with 409 while the recommendation is still pending: the document is the
    consequence of a human decision, not a way around it.

    Nothing is sent anywhere. The file is handed to the buyer, who issues it.
    """
    from agents.procurement.po import NotApproved, build

    conn = connect()
    try:
        pdf = build(conn, reco_id, supplier_code=supplier.strip() or None)
    except NotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        conn.close()

    name = f"PO-{reco_id}-{supplier.strip()}" if supplier.strip() else f"PO-{reco_id}"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )


class ApprovalIn(BaseModel):
    approver: str


@router.post("/api/recommendations/{reco_id}/approve")
def approve_recommendation(reco_id: int, body: ApprovalIn) -> Dict:
    """
    Records a decision. It does not order anything -- there is no code in this
    project that can contact a supplier.
    """
    if not body.approver.strip():
        raise HTTPException(400, "an approval needs a name against it")
    with pooled() as conn:
        ok = approve(conn, reco_id, body.approver.strip())
    if not ok:
        raise HTTPException(409, "that recommendation is not pending approval")
    return {"id": reco_id, "status": "APPROVED", "approved_by": body.approver.strip(),
            "note": "Recorded in our database. No supplier has been contacted."}


# ── the pipeline, streamed ────────────────────────────────────────────────────


@router.get("/api/recommendations/{reco_id}")
def recommendation_detail(reco_id: int) -> Dict:
    """
    Everything the recommendation page needs, assembled in one call.

    The five evidence sections come from four different agents, and a page that
    fetched them separately would render half a story while the rest loaded.
    """
    with pooled() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT r.*, c.mpn AS original_mpn, c.category, c.description
                 FROM platform.purchase_recommendations r
                 JOIN erp.components c ON c.id = r.original_component_id
                WHERE r.id = %s""",
            (reco_id,),
        )
        found = rows(cur)
        if not found:
            raise HTTPException(404, "no such recommendation")
        reco = found[0]
        component_id = reco["original_component_id"]

        cur.execute(
            """SELECT s.name AS supplier, s.country, lc.mpn, l.quantity,
                      l.unit_price, l.line_total, l.lead_time_days,
                      l.expected_arrival, l.supplier_reliability,
                      sc.on_time, sc.late, sc.deliveries, sc.lead_time_padding
                 FROM platform.purchase_recommendation_lines l
                 JOIN erp.suppliers s   ON s.id = l.supplier_id
                 JOIN erp.components lc ON lc.id = l.component_id
                 LEFT JOIN platform.supplier_scores sc ON sc.supplier_id = l.supplier_id
                WHERE l.recommendation_id = %s
                ORDER BY l.quantity DESC""",
            (reco_id,),
        )
        lines = rows(cur)

        cur.execute(
            """SELECT demand_qty, usable_stock, expected_supply, shortage_qty,
                      baseline_shortage_qty, first_shortfall_date, severity,
                      ledger, horizon_start, horizon_end
                 FROM platform.shortages
                WHERE component_id = %s
                ORDER BY created_at DESC LIMIT 1""",
            (component_id,),
        )
        shortage = (rows(cur) or [None])[0]

        cur.execute(
            """SELECT c.mpn, c.manufacturer, c.standard_cost, c.country_of_origin,
                      a.verdict, a.compatibility_score, a.rank, a.sourcing_note, a.checks
                 FROM platform.alternatives a
                 JOIN erp.components c ON c.id = a.candidate_component_id
                WHERE a.original_component_id = %s
                ORDER BY a.rank""",
            (component_id,),
        )
        alternatives = rows(cur)

        cur.execute(
            """SELECT period_month, committed_qty, forecast_qty, net_demand_qty, method
                 FROM platform.demand_forecasts
                WHERE component_id = %s
                ORDER BY period_month""",
            (component_id,),
        )
        forecast = rows(cur)

        cur.execute(
            """SELECT DISTINCT ON (s.id) s.id, s.name, s.country,
                      sc.score, sc.on_time, sc.late, sc.deliveries,
                      sc.avg_days_late, sc.lead_time_padding,
                      supc.unit_price, supc.lead_time_days, supc.stock_available
                 FROM erp.suppliers s
                 JOIN erp.supplier_components supc ON supc.supplier_id = s.id
                 LEFT JOIN platform.supplier_scores sc ON sc.supplier_id = s.id
                WHERE supc.component_id = (
                        SELECT component_id FROM platform.purchase_recommendation_lines
                         WHERE recommendation_id = %s LIMIT 1)
                ORDER BY s.id, supc.unit_price""",
            (reco_id,),
        )
        suppliers_considered = rows(cur)

        cur.execute(
            """SELECT e.external_id, e.headline, e.published_at,
                      i.match_basis, i.origin_country, i.risk_level
                 FROM platform.event_impacts i
                 JOIN platform.external_events e ON e.id = i.event_id
                WHERE i.component_id = %s
                ORDER BY e.published_at DESC LIMIT 1""",
            (component_id,),
        )
        cause = (rows(cur) or [None])[0]

    return {
        "recommendation": reco, "lines": lines, "shortage": shortage,
        "alternatives": alternatives, "forecast": forecast,
        "suppliers_considered": suppliers_considered, "cause": cause,
    }
