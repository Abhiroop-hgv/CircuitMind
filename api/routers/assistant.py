"""
Question answering. Runs on the restricted database role.
"""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.assistant.agent import Assistant, AssistantError
from db.connection import connect_readonly

router = APIRouter()

class AskIn(BaseModel):
    question: str


@router.post("/api/ask")
def ask(body: AskIn) -> Dict:
    """
    A question in English, answered from the same tables the dashboard reads.

    Deliberately not pooled. The assistant holds its connection across several
    seconds of model latency, and the pool has eight slots; two people asking
    questions should not be able to stall every other page in the app.

    The tool calls come back with the answer so the interface can show its
    working -- an answer nobody can audit is worth as little as a
    recommendation nobody can audit.
    """
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="ask something")

    # The restricted role, not the application's own. The assistant answers
    # questions; it has no business being able to change an answer.
    conn = connect_readonly()
    try:
        return Assistant(conn).ask(question)
    except AssistantError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    finally:
        conn.close()
