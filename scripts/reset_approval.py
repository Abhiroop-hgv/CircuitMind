"""
Put the demo back to "waiting for a decision".

Rehearsing the approval step consumes the thing being demonstrated: once a
recommendation is approved the dashboard opens on a green chip and there is
nothing left to sign. `demo.py` fixes that by rebuilding the whole chain, which
takes a minute and spends model calls on an article it has already read.

This is the cheap version. It only changes status, so it is the right tool
between rehearsals and the wrong one if the underlying data has moved.

    python scripts/reset_approval.py           put the newest one back
    python scripts/reset_approval.py --all     put every one back
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db.connection import connect


def main() -> int:
    every = "--all" in sys.argv

    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT id, status, approved_by
                         FROM platform.purchase_recommendations
                        ORDER BY id DESC""")
        rows = cur.fetchall()

        if not rows:
            print("  No recommendations at all. Run: python scripts/demo.py")
            conn.close()
            return 1

        # The newest one only, unless asked for all. Reaching past it to reset
        # an older one would leave two rows pending, which is not the state the
        # demo opens in -- and re-running this should be a no-op, not a way to
        # slowly un-approve the whole table.
        targets = [r for r in rows if r[1] == "APPROVED"] if every else (
            [rows[0]] if rows[0][1] == "APPROVED" else [])

        if not targets:
            pending = [r[0] for r in rows if r[1] != "APPROVED"]
            print(f"  Nothing to reset -- already pending: {pending}")
            conn.close()
            return 0

        for reco_id, _, who in targets:
            cur.execute("""UPDATE platform.purchase_recommendations
                              SET status = 'PENDING_APPROVAL',
                                  approved_by = NULL, approved_at = NULL
                            WHERE id = %s""", (reco_id,))
            print(f"  #{reco_id} was approved by {who}, now pending")

    conn.commit()

    with conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*) FROM platform.purchase_recommendations
                        WHERE status = 'PENDING_APPROVAL'""")
        print(f"\n  waiting for approval: {cur.fetchone()[0]}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
