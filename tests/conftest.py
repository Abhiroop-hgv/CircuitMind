"""
Shared fixtures.

The suite is split by what a test needs, because that decides whether it can be
trusted to run anywhere:

    pure        no database, no network. Runs in milliseconds, always.
    db          needs Postgres on 5433. Skipped, not failed, when it is absent.

Nothing here talks to Groq. A test whose result depends on a language model is
not a regression test, it is a weather report.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def samples() -> Path:
    return ROOT / "samples"


@pytest.fixture(scope="session")
def conn():
    """A database connection, or a skip if Postgres is not running."""
    try:
        from db.connection import connect
        c = connect()
    except Exception as exc:                       # noqa: BLE001
        pytest.skip(f"database not available: {exc}")
    yield c
    c.close()
