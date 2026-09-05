"""
Turning what a document said into a part we actually hold.

The parser hands back `"STM32F407VGT6"`. The rest of the system needs
`component_id = 1`. That gap is where a BOM intake quietly goes wrong, so the
matching is deliberately narrow and every outcome is recorded.

Three outcomes, and no fourth:

    EXACT       the string matches erp.components.mpn as written
    NORMALISED  matches after case-folding, whitespace removal, and stripping a
                packaging suffix a distributor added (-TR, /TR, -ND, -CT-ND)
    UNKNOWN     nothing matched. Recorded with the raw text, never guessed at

What this deliberately does NOT do is fuzzy matching. `STM32F407VGT6` and
`STM32F407VET6` differ by one character and are different chips -- one has
512 KB of flash, the other 1 MB. Any edit-distance match close enough to catch
a typo is also close enough to catch a genuinely different part, and the failure
is silent. An unmatched line is cheap to fix by hand; a wrongly matched one ends
up on a board.

Semantic search over descriptions is the right tool for UNKNOWN lines -- that is
what the vector search in CircuitMind does well, and it belongs in phase 5. It
should propose candidates for a human, not resolve them automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

EXACT = "EXACT"
NORMALISED = "NORMALISED"
UNKNOWN = "UNKNOWN"

# Suffixes distributors bolt onto a manufacturer's part number for packaging or
# their own catalogue. Stripping these is safe: they never change the die.
_PACKAGING_SUFFIXES = (
    "-CT-ND", "-1-ND", "-ND",          # DigiKey catalogue suffixes
    "-TR", "/TR", "-T&R", "-TRPBF",    # tape and reel
    "-REEL", "-TAPE", "-BULK", "-TUBE",
)


def normalise(mpn: str) -> str:
    """Case-fold, strip whitespace and punctuation noise, drop packaging tails."""
    out = re.sub(r"\s+", "", (mpn or "").upper()).strip(".,;:")
    for suffix in _PACKAGING_SUFFIXES:
        if out.endswith(suffix) and len(out) > len(suffix) + 3:
            out = out[: -len(suffix)]
            break
    return out


@dataclass
class Resolved:
    line_number: int
    reference_designator: str
    mpn_raw: str
    description: str
    quantity_per_board: int
    component_id: Optional[int] = None
    matched_mpn: str = ""
    category: str = ""
    resolution: str = UNKNOWN
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.component_id is not None


def _catalogue(conn) -> Dict[str, tuple]:
    """Every part we hold, keyed both as written and normalised."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, mpn, category FROM erp.components")
        rows = cur.fetchall()

    index: Dict[str, tuple] = {}
    for component_id, mpn, category in rows:
        index[mpn] = (component_id, mpn, category, EXACT)
    for component_id, mpn, category in rows:
        key = normalise(mpn)
        # An exact key always wins; only fill a normalised key if it is free.
        if key not in index:
            index[key] = (component_id, mpn, category, NORMALISED)
    return index


def _quantity(raw) -> int:
    """
    Quantity per board, with zero preserved.

    A missing or unreadable quantity means one -- a BOM line exists because the
    part is fitted. But an explicit zero is a DNP line: the part is on the
    drawing and must not be bought. Clamping that to one, which this did until
    a real BOM with DNP rows went through it, quietly orders parts nobody asked
    for.
    """
    try:
        qty = int(raw)
    except (TypeError, ValueError):
        return 1
    return 0 if qty == 0 else max(1, qty)


def resolve_lines(conn, rows: List[dict]) -> List[Resolved]:
    """Match every parsed BOM line against the component catalogue."""
    index = _catalogue(conn)
    out: List[Resolved] = []

    for row in rows:
        raw = (row.get("mpn") or "").strip()
        item = Resolved(
            line_number=row.get("line_number", len(out) + 1),
            reference_designator=row.get("reference_designator", "") or "",
            mpn_raw=raw,
            description=row.get("description", "") or "",
            quantity_per_board=_quantity(row.get("quantity", 1)),
        )

        hit = index.get(raw) or index.get(normalise(raw))
        if hit:
            component_id, matched, category, how = hit
            item.component_id = component_id
            item.matched_mpn = matched
            item.category = category
            item.resolution = EXACT if matched == raw else NORMALISED
            if item.resolution == NORMALISED:
                item.note = f"document said '{raw}', catalogue holds '{matched}'"
        else:
            item.resolution = UNKNOWN
            item.note = "not in the component catalogue"

        out.append(item)

    return out


def summarise(items: List[Resolved]) -> Dict[str, int]:
    return {
        "total": len(items),
        EXACT: sum(1 for i in items if i.resolution == EXACT),
        NORMALISED: sum(1 for i in items if i.resolution == NORMALISED),
        UNKNOWN: sum(1 for i in items if i.resolution == UNKNOWN),
    }
