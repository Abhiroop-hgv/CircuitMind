"""
The HTTP layer: assembly only.

This file used to be eight hundred lines holding every endpoint, the SSE
plumbing, the pipeline orchestration and a JSON serialisation fix. Nothing was
wrong with any one of them; the problem was that they were together, so a change
to how a purchase order is numbered sat in the same file as the CORS policy.

What lives where now:

    config.py         values the whole API agrees on
    serialization.py  database rows to JSON the browser can use
    streaming.py      server-sent events for the long-running runs
    pipeline.py       the shared tail both pipelines end in
    routers/          the endpoints, grouped by subject

Every URL is unchanged. This was a move, not a rewrite: the route bodies were
lifted verbatim rather than retyped, because retyping is where a refactor
changes behaviour by accident.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI                                    # noqa: E402
from fastapi.middleware.cors import CORSMiddleware             # noqa: E402

from api.routers import (assistant, bom, catalogue,            # noqa: E402
                         health, recommendations, runs)
from db.connection import close_pool, get_pool                 # noqa: E402

app = FastAPI(title="Supply-Chain Intelligence Layer", version="1.0")

# The dev front end runs on its own port. In production both are served from one
# origin and this list goes away.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173",
                   "http://127.0.0.1:3000", "http://127.0.0.1:5173",
                   "https://circuit-mind.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Order matters only for readability: every path is distinct, so no route here
# can shadow another.
app.include_router(health.router)
app.include_router(catalogue.router)
app.include_router(recommendations.router)
app.include_router(assistant.router)
app.include_router(runs.router)
app.include_router(bom.router)


def _keep_alive() -> None:
    """Self-ping on Render every 30s so the free instance does not go cold."""
    time.sleep(15)
    url = "https://team-satyatma.onrender.com/api/health"
    while True:
        try:
            requests.get(url, timeout=10)
        except Exception:
            pass
        time.sleep(30)


@app.on_event("startup")
def _open_pool() -> None:
    get_pool()
    threading.Thread(target=_keep_alive, daemon=True).start()


@app.on_event("shutdown")
def _close_pool() -> None:
    close_pool()
