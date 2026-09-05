"""
Build the dummy ERP from scratch.

    python scripts/init_db.py

Drops and recreates the erp / platform schemas, loads master data, then
generates the transactional volume. Safe to re-run; it is meant to be re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import seed_orders            # noqa: E402
from db.connection import connect, database_url  # noqa: E402

DB_DIR = ROOT / "db"


def run_sql_file(conn, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"  applied {path.name}")


def main() -> int:
    print(f"target: {database_url()}")
    with connect() as conn:
        print("schema")
        run_sql_file(conn, DB_DIR / "schema.sql")
        print("master data")
        run_sql_file(conn, DB_DIR / "seed_master.sql")
        print("migrations")
        for path in sorted((DB_DIR / "migrations").glob("*.sql")):
            run_sql_file(conn, path)
        print("generated data")
        seed_orders.seed(conn)
    print("done. run: python scripts/verify.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
