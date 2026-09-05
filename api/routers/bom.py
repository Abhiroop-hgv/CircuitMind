"""
BOM intake: preview a file, then run a board through the pipeline.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi.responses import StreamingResponse
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from agents.bom_intake.buildability import BuildabilityAgent
from agents.bom_intake.intake import ingest
from agents.bom_intake.resolve import UNKNOWN
from agents.bom_intake.similarity import rank
from api.config import TODAY
from api.pipeline import _finish
from api.serialization import rows
from api.streaming import _stream, sse
from db.connection import connect, pooled

router = APIRouter()

def _suggest_for(conn, resolved) -> Dict:
    """Catalogue candidates for each unmatched line, keyed by line number."""
    unknown = [r for r in resolved if r.resolution == UNKNOWN]
    if not unknown:
        return {}
    with conn.cursor() as cur:
        cur.execute("""SELECT id, mpn, manufacturer, category, description, specs
                         FROM erp.components WHERE lifecycle = 'ACTIVE'""")
        parts = rows(cur)
    out: Dict = {}
    for line in unknown:
        top = rank(f"{line.mpn_raw} {line.description}", parts, top_k=5)
        out[str(line.line_number)] = [
            {"mpn": r["mpn"], "manufacturer": r["manufacturer"],
             "category": r["category"], "description": r["description"],
             "score": round(float(score), 3)}
            for r, score in top
        ]
    return out


@router.post("/api/bom/preview")
async def bom_preview(file: UploadFile = File(...)) -> Dict:
    """Parse and resolve without writing anything. Lets the UI show a preview."""
    from agents.bom_intake.parser import parse_bom_file
    from agents.bom_intake.resolve import resolve_lines

    suffix = Path(file.filename or "bom.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        path = tmp.name
    try:
        try:
            parsed = parse_bom_file(path)
        except RuntimeError as exc:
            # The parser refuses a file it cannot read and says why -- a scan
            # with no text layer, an image, a format we do not handle. That
            # sentence is the useful part; letting it become a 500 throws it
            # away and leaves the user with "Internal Server Error".
            raise HTTPException(status_code=400, detail=str(exc))
        with pooled() as conn:
            resolved = resolve_lines(conn, parsed)
        return {
            "filename": file.filename,
            "lines": [{"line_number": r.line_number, "ref": r.reference_designator,
                       "mpn_raw": r.mpn_raw, "matched_mpn": r.matched_mpn,
                       "qty_per_board": r.quantity_per_board,
                       "description": r.description, "resolution": r.resolution,
                       "note": r.note} for r in resolved],
            "unknown": [r.mpn_raw for r in resolved if r.resolution == UNKNOWN],
            # Ranked catalogue parts for anything we could not match, so the
            # unknown lines can be resolved on screen instead of blocking the
            # run. Suggestions only: nothing is chosen automatically.
            "suggestions": _suggest_for(conn, resolved),
        }
    finally:
        Path(path).unlink(missing_ok=True)


@router.post("/api/run/bom")
async def run_bom(file: UploadFile = File(...), sku: str = Form(...),
                  name: str = Form(...), qty: int = Form(...),
                  need_by: str = Form(...), approver: str = Form(""),
                  constraints: str = Form(""),
                  overrides: str = Form("")) -> StreamingResponse:
    # Non-negotiables the engineer set before the run. Bad JSON is treated as
    # no constraints rather than failing the run: the gate is optional, and
    # losing a build check over a malformed field would be the wrong trade.
    # Quantity edits and unknown-part resolutions made on screen.
    edits: Dict = {}
    if overrides.strip():
        try:
            parsed_edits = json.loads(overrides)
            if isinstance(parsed_edits, dict):
                edits = parsed_edits
        except json.JSONDecodeError:
            edits = {}

    gate: Dict = {}
    if constraints.strip():
        try:
            parsed_gate = json.loads(constraints)
            if isinstance(parsed_gate, dict):
                gate = {k: v for k, v in parsed_gate.items()
                        if v not in (None, "", [])}
        except json.JSONDecodeError:
            gate = {}

    suffix = Path(file.filename or "bom.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        path = tmp.name
    need_by_date = datetime.strptime(need_by, "%Y-%m-%d").date()

    def work(emit):
        try:
            with pooled() as conn:
                emit("stage", stage="parse", status="running", detail="reading the file")
                with conn.cursor() as cur:
                    cur.execute("""DELETE FROM platform.shortages WHERE build_request_id IN
                                     (SELECT id FROM platform.build_requests
                                       WHERE product_sku = %s)""", (sku,))
                    cur.execute("DELETE FROM platform.build_requests WHERE product_sku = %s",
                                (sku,))
                conn.commit()

                intake = ingest(conn, path, overrides=edits, sku=sku, name=name,
                                build_qty=qty, need_by=need_by_date)
                emit("stage", stage="parse", status="done",
                     counts=intake.counts, product_id=intake.product_id,
                     status_flag=intake.status,
                     lines=[{"ref": l.reference_designator, "mpn": l.mpn_raw,
                             "qty": l.quantity_per_board, "resolution": l.resolution,
                             "note": l.note} for l in intake.lines],
                     unknown=[l.mpn_raw for l in intake.unknown])

                emit("stage", stage="build", status="running",
                     detail="checking against what is already promised")
                build = BuildabilityAgent(conn, today=TODAY)
                assessment = build.assess(intake.request_id)
                build.persist(assessment)
                emit("stage", stage="build", status="done",
                     unknown=assessment.unknown_mpns,
                     lines=[{"mpn": l.mpn, "per_board": l.qty_per_board,
                             "required": l.required,
                             "stock": l.shortage.usable_stock,
                             "shortage": l.shortage.shortage_qty,
                             "baseline": l.shortage.baseline_shortage_qty,
                             "severity": l.shortage.severity,
                             "first_short": str(l.shortage.first_shortfall_date)
                             if l.shortage.first_shortfall_date else None}
                            for l in sorted(assessment.lines,
                                            key=lambda x: -x.shortage.shortage_qty)])

                blocked = assessment.blocked_by
                if not blocked:
                    emit("complete", message="Everything is covered. Nothing to buy.")
                    return

                shortage = blocked[0].shortage
                with conn.cursor() as cur:
                    cur.execute("""SELECT COALESCE(array_agg(DISTINCT x), '{}')
                                     FROM platform.event_impacts ei
                                     CROSS JOIN LATERAL unnest(ei.affected_supplier_ids) AS x
                                    WHERE ei.risk_level IN ('HIGH','MEDIUM')""")
                    affected = list(cur.fetchone()[0] or [])
                if affected:
                    emit("inherited", suppliers=len(affected),
                         message="Suppliers still flagged by a live disruption are "
                                 "excluded here too.")
                _finish(conn, emit, shortage, affected, approver, None,
                        constraints=gate)

                # the unmatched parts, ranked for a human
                if assessment.unknown_mpns:
                    with conn.cursor() as cur:
                        cur.execute("""SELECT id, mpn, manufacturer, category, description, specs
                                         FROM erp.components WHERE lifecycle='ACTIVE'""")
                        parts = rows(cur)
                    suggestions = []
                    for line in intake.unknown:
                        top = rank(f"{line.mpn_raw} {line.description}", parts, top_k=3)
                        suggestions.append({
                            "mpn": line.mpn_raw, "description": line.description,
                            "candidates": [{"mpn": r["mpn"], "category": r["category"],
                                            "score": s} for r, s in top]})
                    emit("unmatched", suggestions=suggestions)
        finally:
            Path(path).unlink(missing_ok=True)

    return _stream(work)
