"""
The shared tail of both pipelines.

A news event and a new BOM arrive differently and mean different things, but
once either has produced a shortage the rest is identical: find what else fits,
price it, and stop for a person. That sameness is deliberate, so it lives in one
function rather than being written twice and drifting.
"""

from __future__ import annotations

from typing import Dict, Optional

from agents.component.agent import ComponentAgent, handoff_to_procurement
from agents.procurement.agent import ProcurementAgent, approve
from agents.procurement.reliability import compute as compute_scores
from agents.procurement.reliability import persist as persist_scores

from api.config import TODAY

def _reset_platform(conn, include_events: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM platform.purchase_recommendations")
        cur.execute("DELETE FROM platform.alternatives")
        cur.execute("DELETE FROM platform.shortages")
        if include_events:
            cur.execute("DELETE FROM platform.event_impacts")
            cur.execute("UPDATE platform.external_events "
                        "SET status='NEW', extracted='{}'::jsonb")
    conn.commit()


def _finish(conn, emit, shortage, affected, approver, event_id,
            constraints: Optional[Dict] = None) -> None:
    """Substitution, sourcing and the human gate -- shared by both pipelines."""
    emit("stage", stage="component", status="running", detail="checking what else fits")
    comp = ComponentAgent(conn)
    candidates = comp.assess(shortage.component_id, affected,
                             extra_constraints=constraints)
    comp.persist(event_id, shortage.component_id, candidates)
    emit("stage", stage="component", status="done",
         boards=[b.sku for b in candidates[0].boards] if candidates else [],
         constraints=constraints or {},
         candidates=[{"mpn": c.mpn, "manufacturer": c.manufacturer,
                      "cost": c.standard_cost, "verdict": c.verdict, "fit": c.score,
                      "origin": c.country_of_origin, "note": c.sourcing_note,
                      "why": (c.first_failure.name + ": needs " + c.first_failure.required
                              + ", has " + c.first_failure.actual) if c.first_failure else "",
                      "checks": [{"board": b.sku, "verdict": b.verdict,
                                  "checks": [{"name": k.name, "required": k.required,
                                              "actual": k.actual, "ok": k.ok}
                                             for k in b.checks]}
                                 for b in c.boards]}
                     for c in candidates])

    emit("stage", stage="procurement", status="running", detail="scoring suppliers and pricing")
    persist_scores(conn, compute_scores(conn))
    proc = ProcurementAgent(conn, today=TODAY)
    result = proc.recommend(component_id=shortage.component_id, mpn=shortage.mpn,
                            qty=shortage.shortage_qty,
                            need_by=shortage.first_shortfall_date,
                            alternatives=handoff_to_procurement(conn, shortage.component_id),
                            affected_suppliers=affected)
    reco_id = proc.persist(event_id, shortage.component_id, shortage.shortage_qty,
                           shortage.first_shortfall_date, result)
    plan = result["plan"]
    emit("stage", stage="procurement", status="done",
         recommendation_id=reco_id, strategy=plan.name,
         rationale=result["rationale"], considered=result["considered"],
         total_cost=plan.total_cost, latest_arrival=str(plan.latest_arrival),
         requires_bom_change=plan.requires_bom_change,
         lines=[{"supplier": l.supplier, "mpn": l.mpn, "quantity": l.quantity,
                 "unit_price": l.unit_price, "total": l.total,
                 "arrival": str(l.arrival), "score": l.score} for l in plan.lines])

    if approver.strip():
        approve(conn, reco_id, approver.strip())
        emit("approved", recommendation_id=reco_id, by=approver.strip())
    emit("complete", recommendation_id=reco_id, message="Pipeline finished.")


# ── BOM intake ────────────────────────────────────────────────────────────────
