"""
The news pipeline, streamed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Form

from agents.demand.agent import DemandAgent
from agents.intelligence.agent import IntelligenceAgent
from agents.intelligence.extract import FixtureExtractor
from agents.supply_risk.agent import SupplyRiskAgent
from api.config import TODAY, WATCH_MPN
from api.pipeline import _finish, _reset_platform
from api.serialization import rows
from api.streaming import _stream, sse
from db.connection import connect, pooled

router = APIRouter()

@router.post("/api/run/news")
def run_news(external_id: str = Form("EVT-2026-09-02-001"),
             use_model: bool = Form(True),
             approver: str = Form("")) -> StreamingResponse:
    """The disruption pipeline, one SSE message per step."""

    def work(emit):
        with pooled() as conn:
            _reset_platform(conn, include_events=True)

            if use_model:
                from agents.intelligence.groq_extract import DEFAULT_MODEL, GroqExtractor
                extractor = GroqExtractor(model=DEFAULT_MODEL)
            else:
                extractor = FixtureExtractor()

            emit("stage", stage="read", status="running",
                 detail=f"reading the notice with {extractor.name}")

            agent = IntelligenceAgent(conn, extractor, today=TODAY, explain=False)
            candidates = [e for e in agent.pending_events() if e["external_id"] == external_id]
            if not candidates:
                raise RuntimeError(f"no unread event {external_id}")
            event = candidates[0]
            emit("article", headline=event["headline"], body=event["body"],
                 source=event["source"], published=str(event["published_at"]))

            started = datetime.now()
            outcome = agent.analyse(event)
            e = outcome.extraction
            emit("stage", stage="read", status="done",
                 seconds=round((datetime.now() - started).total_seconds(), 1),
                 extraction={"event_type": e.event_type, "countries": e.countries,
                             "categories": e.component_categories,
                             "effective_date": e.effective_date,
                             "delay_days": e.expected_delay_days,
                             "confidence": e.confidence},
                 impacts=[{"mpn": i["match"].mpn, "risk": i["risk_level"],
                           "boards": i["match"].product_skus,
                           "at_risk_qty": i["match"].at_risk_qty,
                           "basis": i["match"].basis,
                           "rule": i["rule_inputs"].get("rule", "")}
                          for i in outcome.impacts])

            # --- demand ---------------------------------------------------
            emit("stage", stage="demand", status="running", detail="forecasting demand")
            demand_agent = DemandAgent(conn, today=TODAY)
            forecasts = demand_agent.forecast_products()
            demands = demand_agent.explode(forecasts)
            demand_agent.persist(demands, forecasts)
            watch = next((d for d in demands if d.mpn == WATCH_MPN), None)
            emit("stage", stage="demand", status="done",
                 method=forecasts[0].result.method if forecasts else "n/a",
                 committed=watch.total_committed if watch else 0,
                 uncovered=sum(watch.uncovered) if watch else 0,
                 net=watch.total_net if watch else 0)

            # --- shortage -------------------------------------------------
            emit("stage", stage="risk", status="running", detail="netting the ledger")
            risk = SupplyRiskAgent(conn, today=TODAY)
            shortage = None
            for flag in risk.handoffs(outcome.event_id):
                s = risk.assess(flag)
                risk.persist(flag["event_id"], s)
                if s.mpn == WATCH_MPN:
                    shortage = s
            if shortage is None:
                emit("stage", stage="risk", status="done", shortage=None)
                emit("complete", message="No shortage. Nothing to solve.")
                return
            emit("stage", stage="risk", status="done",
                 shortage={"mpn": shortage.mpn, "demand": shortage.demand_qty,
                           "usable_stock": shortage.usable_stock,
                           "lost": shortage.incoming_lost,
                           "baseline": shortage.baseline_shortage_qty,
                           "shortage": shortage.shortage_qty,
                           "severity": shortage.severity,
                           "first_short": str(shortage.first_shortfall_date),
                           "ledger": shortage.ledger})

            affected = [sid for i in outcome.impacts if i["match"].mpn == WATCH_MPN
                        for sid in i["match"].supplier_ids]
            _finish(conn, emit, shortage, affected, approver, outcome.event_id)

    return _stream(work)
