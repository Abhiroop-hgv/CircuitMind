"""
Read-only views of what the ERP holds and what the analysis found.
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter

from agents.procurement.reliability import compute as compute_scores
from agents.procurement.reliability import persist as persist_scores
from api.serialization import rows
from db.connection import pooled

router = APIRouter()

@router.get("/api/events")
def events() -> List[Dict]:
    with pooled() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, external_id, source_type, headline, body,
                              published_at, status, is_synthetic,
                              extracted->>'event_type'  AS event_type,
                              extracted->>'_skipped_reason' AS skipped_reason
                         FROM platform.external_events ORDER BY published_at DESC""")
        return rows(cur)


@router.get("/api/impacts")
def impacts() -> List[Dict]:
    with pooled() as conn, conn.cursor() as cur:
        cur.execute("""SELECT i.id, e.external_id, c.mpn, c.category, i.risk_level,
                              i.at_risk_qty, i.expected_delay_days, i.match_basis,
                              i.origin_country, i.rule_inputs, i.explanation
                         FROM platform.event_impacts i
                         JOIN erp.components c ON c.id = i.component_id
                         JOIN platform.external_events e ON e.id = i.event_id
                        ORDER BY i.risk_level, c.mpn""")
        return rows(cur)


@router.get("/api/shortages")
def shortages() -> List[Dict]:
    with pooled() as conn, conn.cursor() as cur:
        cur.execute("""SELECT s.id, c.mpn, s.demand_qty, s.usable_stock, s.expected_supply,
                              s.shortage_qty, s.baseline_shortage_qty,
                              s.first_shortfall_date, s.severity, s.ledger,
                              s.event_id, s.build_request_id
                         FROM platform.shortages s
                         JOIN erp.components c ON c.id = s.component_id
                        ORDER BY s.shortage_qty DESC""")
        return rows(cur)


@router.get("/api/suppliers")
def suppliers() -> List[Dict]:
    with pooled() as conn:
        persist_scores(conn, compute_scores(conn))
        with conn.cursor() as cur:
            cur.execute("""SELECT s.id, s.name, s.country, s.supplier_type,
                                  sc.deliveries, sc.on_time, sc.late, sc.score,
                                  sc.avg_days_late, sc.lead_time_padding
                             FROM erp.suppliers s
                             LEFT JOIN platform.supplier_scores sc ON sc.supplier_id = s.id
                            ORDER BY sc.score DESC NULLS LAST, s.name""")
            return rows(cur)
