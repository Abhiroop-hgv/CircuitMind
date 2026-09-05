"""
The Intelligence Agent.

    event -> extract (LLM) -> match (SQL) -> score (rules) -> persist -> explain

Its whole job is to answer "does this matter to us, and to what exactly?".
It does not size shortages and it does not decide purchases -- it writes
platform.event_impacts and hands off to the Supply Risk Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from psycopg.types.json import Jsonb

from .match import ComponentMatch, MatchResult, component_categories, match
from .schema import EventExtraction
from .score import score

HORIZON_DAYS = 60

EXPLAIN_MODEL = "claude-opus-5"
EXPLAIN_SYSTEM = """\
You write one short paragraph for a supply chain manager, explaining a finding
the system has already made.

You will be given the finding as structured data. Use ONLY the numbers in it.
Do not add figures, do not estimate, do not speculate about what happens next,
and do not recommend an action -- a later stage of the system does that.

Three sentences at most. Plain language. Name the part, the supplier, and what
is in flight.\
"""


@dataclass
class EventOutcome:
    event_id: int
    external_id: str
    headline: str
    extraction: Optional[EventExtraction] = None
    extractor: str = ""
    result: Optional[MatchResult] = None
    impacts: List[Dict] = field(default_factory=list)
    status: str = "IGNORED"

    @property
    def worst_risk(self) -> str:
        order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        if not self.impacts:
            return "-"
        return max((i["risk_level"] for i in self.impacts), key=lambda r: order[r])


class IntelligenceAgent:
    def __init__(self, conn, extractor, today: Optional[date] = None, explain=True,
                 explainer=None):
        """
        explainer: optional callable taking the computed facts dict and returning
        a sentence. Leave it None to use the Anthropic API. Passing one lets a
        local model -- or nothing at all -- write the summary instead.
        """
        self.conn = conn
        self.extractor = extractor
        self.today = today or date(2026, 9, 3)
        self.horizon_end = self.today + timedelta(days=HORIZON_DAYS)
        self.explain = explain
        self.explainer = explainer
        self._categories = component_categories(conn)
        self._llm = None

    # -- public ------------------------------------------------------------

    def pending_events(self) -> List[Dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id, external_id, source, source_type, headline, body, published_at
                     FROM platform.external_events
                    WHERE status = 'NEW'
                    ORDER BY published_at DESC"""
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def analyse(self, event: Dict) -> EventOutcome:
        outcome = EventOutcome(
            event_id=event["id"],
            external_id=event["external_id"],
            headline=event["headline"],
        )

        # 1. language -> structure
        extraction, extractor_name = self.extractor.extract(event, self._categories)
        outcome.extraction = extraction
        outcome.extractor = extractor_name

        # 2. structure -> our entities
        result = match(self.conn, extraction, self.horizon_end)
        outcome.result = result

        # 3. exposure rules, per affected component
        for m in result.components:
            risk, rule_inputs = score(self.conn, m)
            outcome.impacts.append(
                {
                    "match": m,
                    "risk_level": risk,
                    "rule_inputs": rule_inputs,
                    "explanation": None,
                }
            )

        # 4. a sentence a human can read, grounded in what we just computed
        if self.explain:
            for impact in outcome.impacts:
                impact["explanation"] = self._explain(outcome, impact)

        outcome.status = "ANALYZED" if outcome.impacts else "IGNORED"
        self._persist(outcome)
        return outcome

    def run(self) -> List[EventOutcome]:
        return [self.analyse(e) for e in self.pending_events()]

    # -- internals ---------------------------------------------------------

    def _explain(self, outcome: EventOutcome, impact: Dict) -> str:
        m: ComponentMatch = impact["match"]
        facts = {
            "headline": outcome.headline,
            "event_type": outcome.extraction.event_type,
            "effective_date": outcome.extraction.effective_date,
            "component": m.mpn,
            "affected_suppliers": m.supplier_names,
            "boards_using_it": m.product_skus,
            "units_in_flight_from_affected_lane": m.at_risk_qty,
            "expected_delay_days": outcome.extraction.expected_delay_days,
            "risk_level": impact["risk_level"],
            **impact["rule_inputs"],
        }

        if self.explainer is not None:
            return self.explainer(EXPLAIN_SYSTEM, facts)

        if self._llm is None:
            import anthropic

            self._llm = anthropic.Anthropic()

        response = self._llm.messages.create(
            model=EXPLAIN_MODEL,
            max_tokens=1000,
            system=EXPLAIN_SYSTEM,
            messages=[{"role": "user", "content": repr(facts)}],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def _persist(self, outcome: EventOutcome) -> None:
        extraction = outcome.extraction
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE platform.external_events
                      SET extracted = %s, status = %s
                    WHERE id = %s""",
                (
                    Jsonb(
                        {
                            **extraction.model_dump(),
                            "_extractor": outcome.extractor,
                            "_skipped_reason": outcome.result.skipped_reason,
                        }
                    ),
                    outcome.status,
                    outcome.event_id,
                ),
            )

            for impact in outcome.impacts:
                m: ComponentMatch = impact["match"]
                cur.execute(
                    """INSERT INTO platform.event_impacts
                         (event_id, component_id, affected_supplier_ids,
                          affected_product_ids, at_risk_po_ids, at_risk_qty,
                          expected_delay_days, risk_level, rule_inputs,
                          explanation, extractor, match_basis, origin_country)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (event_id, component_id) DO UPDATE SET
                          affected_supplier_ids = EXCLUDED.affected_supplier_ids,
                          affected_product_ids  = EXCLUDED.affected_product_ids,
                          at_risk_po_ids        = EXCLUDED.at_risk_po_ids,
                          at_risk_qty           = EXCLUDED.at_risk_qty,
                          expected_delay_days   = EXCLUDED.expected_delay_days,
                          risk_level            = EXCLUDED.risk_level,
                          rule_inputs           = EXCLUDED.rule_inputs,
                          explanation           = EXCLUDED.explanation,
                          extractor             = EXCLUDED.extractor,
                          match_basis           = EXCLUDED.match_basis,
                          origin_country        = EXCLUDED.origin_country,
                          created_at            = NOW()""",
                    (
                        outcome.event_id,
                        m.component_id,
                        m.supplier_ids,
                        m.product_ids,
                        m.at_risk_po_ids,
                        m.at_risk_qty,
                        extraction.expected_delay_days,
                        impact["risk_level"],
                        Jsonb(impact["rule_inputs"]),
                        impact["explanation"],
                        outcome.extractor,
                        m.basis,
                        m.origin_country,
                    ),
                )
        self.conn.commit()


def handoff(conn, event_id: int) -> List[Dict]:
    """
    What the Supply Risk Agent picks up. Deliberately small: component, the POs
    to treat as late, how many units, and by how long.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.mpn, i.at_risk_po_ids, i.at_risk_qty,
                      i.expected_delay_days, i.risk_level, i.match_basis,
                      i.origin_country
                 FROM platform.event_impacts i
                 JOIN erp.components c ON c.id = i.component_id
                WHERE i.event_id = %s AND i.risk_level IN ('HIGH', 'MEDIUM')
                ORDER BY i.risk_level, c.mpn""",
            (event_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
