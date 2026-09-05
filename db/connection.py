"""
Where the database connection comes from.

Two ways in, because the two callers want opposite things.

  connect()  a fresh connection, closed when the caller is done. What the CLI
             scripts want: one process, one job, then exit.

  pooled()   a connection borrowed from a pool and handed straight back. What
             the API wants.

The API needed the pool for a measurable reason: /api/health runs a single
COUNT(*) and was taking ~154 ms, almost all of it opening a new PostgreSQL
connection. Every endpoint paid that toll on every request. The pool keeps a
few connections open, so the toll is paid once at startup.

The pool is built lazily. Importing this module from a CLI script must not open
connections the script will never use.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from dotenv import load_dotenv

load_dotenv()

# Defaults to a locally installed Postgres on 5432. If you run the bundled
# docker-compose instead, set DATABASE_URL to port 5433 in .env.
DEFAULT_URL = "postgresql://scip:scip@localhost:5432/scip"

SEARCH_PATH = "SET search_path TO erp, platform, public"

_pool = None  # type: Optional[object]


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_URL)


def _configure(conn: psycopg.Connection) -> None:
    """Run once per pooled connection, not per checkout."""
    with conn.cursor() as cur:
        cur.execute(SEARCH_PATH)
    conn.commit()


def connect() -> psycopg.Connection:
    """A new connection with the ERP mirror on the search path."""
    conn = psycopg.connect(database_url())
    with conn.cursor() as cur:
        cur.execute(SEARCH_PATH)
    return conn


def readonly_url() -> Optional[str]:
    return os.getenv("DATABASE_URL_RO")


def connect_readonly() -> psycopg.Connection:
    """
    A connection that the database itself will not let you write with.

    Used by the assistant. Its tools are all SELECTs, but "all of them happen to
    be SELECTs" is a property of the code as written today, and the point of the
    role is to stop depending on that.

    Falls back to the ordinary connection when DATABASE_URL_RO is unset, and
    says so loudly rather than silently downgrading the guarantee. Create the
    role with scripts/create_readonly_role.py.
    """
    url = readonly_url()
    if not url:
        print("WARNING: DATABASE_URL_RO is not set -- the assistant is using the "
              "read-write connection. Run scripts/create_readonly_role.py.")
        return connect()

    conn = psycopg.connect(url)
    with conn.cursor() as cur:
        cur.execute(SEARCH_PATH)
    return conn


def get_pool():
    """The process-wide pool, created on first use."""
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool

        _pool = ConnectionPool(
            conninfo=database_url(),
            min_size=2,
            max_size=8,
            configure=_configure,
            # Fail fast rather than hang a request behind a dead database.
            timeout=10,
            open=True,
        )
    return _pool


@contextmanager
def pooled() -> Iterator[psycopg.Connection]:
    """
    Borrow a connection, hand it back afterwards.

    psycopg's pool rolls back an un-committed transaction on return, so a
    handler that raises cannot leak a half-finished write into the next
    request that borrows the same connection.
    """
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
