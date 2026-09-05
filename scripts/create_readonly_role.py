"""
Create the database role the assistant connects as.

Until now the assistant was read-only because every tool happened to be a
SELECT -- a promise kept by my own discipline, which is not a guarantee anyone
should accept. This makes it structural: the assistant logs in as a role that
the database itself will not allow to write.

Two independent locks, because one of them can be undone by accident:

  privileges   SELECT is granted; INSERT, UPDATE, DELETE and TRUNCATE are never
               granted, and no ownership is transferred.

  read-only    default_transaction_read_only is forced on for the role, so even
  transactions if someone later grants a write privilege by mistake, the
               transaction still refuses to write.

The second lock is the one that matters. Privilege grants drift as schemas grow
-- a new table, a GRANT ALL typed in a hurry -- and this survives that.

Safe to run more than once.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import psycopg                                      # noqa: E402
from psycopg import sql                             # noqa: E402

from db.connection import database_url              # noqa: E402

ROLE = "scip_readonly"
SCHEMAS = ("erp", "platform", "public")
ENV_KEY = "DATABASE_URL_RO"


def readonly_url(password: str) -> str:
    """The same server and database, as the restricted role."""
    parts = urlsplit(database_url())
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 5432
    name = (parts.path or "/scip").lstrip("/")
    return f"postgresql://{ROLE}:{password}@{host}:{port}/{name}"


def write_env(url: str) -> Path:
    env = Path(__file__).resolve().parents[1] / ".env"
    line = f"{ENV_KEY}={url}"
    text = env.read_text(encoding="utf-8") if env.exists() else ""

    if re.search(rf"^{ENV_KEY}=", text, flags=re.M):
        text = re.sub(rf"^{ENV_KEY}=.*$", line, text, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"

    env.write_text(text, encoding="utf-8")
    return env


def main() -> int:
    password = os.getenv("READONLY_PASSWORD") or secrets.token_urlsafe(18)

    # Raw connection rather than connect(): that helper sets the search path,
    # which opens a transaction, and CREATE ROLE wants autocommit.
    conn = psycopg.connect(database_url(), autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
        exists = cur.fetchone() is not None

        # PASSWORD takes no bound parameter, so the value has to be composed
        # into the statement. sql.Literal quotes it properly; a plain f-string
        # here would be an injection waiting for a password with a quote in it.
        verb = "ALTER" if exists else "CREATE"
        print(f"  {'role ' + ROLE + ' exists, resetting' if exists else 'creating role ' + ROLE}")
        cur.execute(sql.SQL("{} ROLE {} WITH LOGIN PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(ROLE), sql.Literal(password)))

        # Lock two: refuse writes at the transaction level, whatever the grants
        # happen to say later.
        cur.execute(f"ALTER ROLE {ROLE} SET default_transaction_read_only = on")

        db = conn.info.dbname
        cur.execute(f'GRANT CONNECT ON DATABASE "{db}" TO {ROLE}')

        for schema in SCHEMAS:
            cur.execute(f"GRANT USAGE ON SCHEMA {schema} TO {ROLE}")
            cur.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {ROLE}")
            # Tables that do not exist yet, created by the owner.
            cur.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                        f"GRANT SELECT ON TABLES TO {ROLE}")
            # Nothing here should ever be creatable by this role.
            cur.execute(f"REVOKE CREATE ON SCHEMA {schema} FROM {ROLE}")

        cur.execute("""SELECT COUNT(*) FROM information_schema.table_privileges
                        WHERE grantee = %s AND privilege_type = 'SELECT'""", (ROLE,))
        readable = cur.fetchone()[0]
        cur.execute("""SELECT COUNT(*) FROM information_schema.table_privileges
                        WHERE grantee = %s
                          AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE')""",
                    (ROLE,))
        writable = cur.fetchone()[0]
    conn.close()

    print(f"  readable tables: {readable}")
    print(f"  write privileges: {writable}   (must be 0)")

    env = write_env(readonly_url(password))
    print(f"  wrote {ENV_KEY} to {env}")

    if writable:
        print("\n  REFUSING to call this done: the role holds write privileges.")
        return 1

    # Prove it rather than assert it.
    print("\n  verifying as the new role:")
    ro = psycopg.connect(readonly_url(password))
    with ro.cursor() as cur:
        cur.execute("SET search_path TO erp, platform, public")
        cur.execute("SELECT COUNT(*) FROM erp.components")
        print(f"    SELECT  -> ok, {cur.fetchone()[0]} components")

    failures = 0
    for label, statement in [
        ("INSERT", "INSERT INTO erp.components (id, mpn, manufacturer, category) "
                   "VALUES (999999, 'HACK-1', 'x', 'MCU')"),
        ("UPDATE", "UPDATE erp.components SET mpn = 'HACK-2' WHERE id = 1"),
        ("DELETE", "DELETE FROM erp.components WHERE id = 1"),
        ("CREATE", "CREATE TABLE erp.hack (id INT)"),
    ]:
        try:
            with ro.cursor() as cur:
                cur.execute(statement)
            ro.rollback()
            print(f"    {label}  -> ALLOWED. This is a failure.")
            failures += 1
        except psycopg.Error as exc:
            ro.rollback()
            reason = str(exc).splitlines()[0][:60]
            print(f"    {label}  -> refused ({reason})")
    ro.close()

    if failures:
        print("\n  the role can write. Not safe to use.")
        return 1

    print("\n  done. Point the assistant at DATABASE_URL_RO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
