"""
Liveness and the overview figures the landing page shows.
"""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter

from agents.supply_risk.agent import SupplyRiskAgent
from api.config import TODAY, WATCH_MPN
from api.serialization import rows
from db.connection import pooled

router = APIRouter()

@router.get("/api/health")
def health() -> Dict:
    with pooled() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM erp.components")
        components = cur.fetchone()[0]
    return {"ok": True, "today": str(TODAY), "components": components}


@router.get("/api/overview")
def overview() -> Dict:
    """The position as it stands: what the ERP would show a planner."""
    with pooled() as conn:
        risk = SupplyRiskAgent(conn, today=TODAY, use_forecast=False)
        with conn.cursor() as cur:
            cur.execute("SELECT id, mpn, description FROM erp.components WHERE mpn = %s",
                        (WATCH_MPN,))
            component = rows(cur)[0]
            cur.execute("""SELECT p.sku, p.name, p.family,
                                  (SELECT COUNT(*) FROM erp.bom b WHERE b.product_id = p.id) AS lines
                             FROM erp.products p WHERE p.active ORDER BY p.sku""")
            products = rows(cur)
            cur.execute("SELECT COUNT(*) FILTER (WHERE status='NEW') AS unread, COUNT(*) AS total "
                        "FROM platform.external_events")
            feed = rows(cur)[0]

        demand = -sum(m.qty for m in risk.demand_movements(component["id"]))
        stock = risk.usable_stock(component["id"])
        arrivals = risk.arrival_movements(component["id"], [], None)

        return {
            "watch": {
                "mpn": component["mpn"],
                "description": component["description"],
                "committed_demand": demand,
                "usable_stock": stock,
                "incoming": [{"ref": m.ref, "qty": m.qty, "when": str(m.when)} for m in arrivals],
                "expected_supply": stock + sum(m.qty for m in arrivals),
                "gap": stock + sum(m.qty for m in arrivals) - demand,
            },
            "products": products,
            "feed": feed,
        }
