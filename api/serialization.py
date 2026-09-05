"""
Turning database rows into JSON the browser can use.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List

def rows(cur) -> List[Dict]:
    """
    Rows as plain dicts, with NUMERIC columns as JSON numbers.

    psycopg hands back Decimal for NUMERIC and the JSON encoder renders those as
    STRINGS -- so a price arrived in the browser as "11.0500" and every
    .toFixed() on it threw. Converting here fixes every endpoint at once rather
    than leaving each caller to coerce.
    """
    cols = [d[0] for d in cur.description]
    return [
        {c: (float(v) if isinstance(v, Decimal) else v) for c, v in zip(cols, r)}
        for r in cur.fetchall()
    ]


# ── read-only views ───────────────────────────────────────────────────────────
