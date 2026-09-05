"""
BOM intake: a document becomes a permanent product in the ERP mirror.

    file -> parse -> resolve against the catalogue -> register as a product
                  -> erp.products + erp.bom

Registering permanently rather than quoting once is the whole point. Once the
board is in `erp.products` with a real BOM, everything else already built starts
watching it for free: the Intelligence Agent traces news to it, the Demand Agent
forecasts it, the Supply Risk Agent nets it. A new product is monitored from the
moment it lands.

ABOUT design_constraints
------------------------
Agent 4 verifies substitutes against `erp.bom.design_constraints` -- what the
BOARD requires. A BOM document does not carry that. It lists part numbers and
quantities; footprint, rail voltage and temperature grade live in the CAD and
PLM systems.

So we derive the only constraints that can be read off the fitted part without
inventing engineering data:

    footprint_id    must match what is fitted -- a different package will not
                    physically mount, and this is readable from the part itself
    pinout_family   where the catalogue records one

and nothing else. We do NOT guess a rail voltage or a temperature grade: a board
running at 5 V and one running at 3.3 V can fit the identical part, and picking
one would be fabricating a requirement that a substitute is then judged against.

The effect is a deliberately WEAK constraint set. A substitute for this board
clears the physical checks and nothing more, and the intake report says so. A
real deployment reads the full constraint set from PLM; deriving it here is a
floor, not a substitute for engineering input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from psycopg.types.json import Jsonb

from .parser import parse_bom_file
from .resolve import UNKNOWN, Resolved, resolve_lines, summarise

# Categories where a substitution changes how the board behaves rather than just
# what it costs. Used to set erp.bom.is_critical, which agent 1 reads when it
# scores exposure.
CRITICAL_CATEGORIES = {
    "MCU", "GATE_DRIVER", "MOSFET", "ETHERNET_PHY", "MODULE_WIFI",
    "CAN_TRANSCEIVER", "FLASH_SPI",
}


@dataclass
class Intake:
    request_id: int
    filename: str
    sku: str
    name: str
    build_qty: int
    need_by: date
    lines: List[Resolved] = field(default_factory=list)
    product_id: Optional[int] = None
    status: str = "PARSED"

    @property
    def unknown(self) -> List[Resolved]:
        return [l for l in self.lines if l.resolution == UNKNOWN]

    @property
    def resolved(self) -> List[Resolved]:
        return [l for l in self.lines if l.ok]

    @property
    def counts(self) -> Dict[str, int]:
        return summarise(self.lines)


def _next_id(conn, table: str) -> int:
    """erp.products and erp.components use assigned integer keys, not identity."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}")
        return cur.fetchone()[0]


def _derive_constraints(conn, component_id: int) -> Dict:
    """The physical checks only -- see the module docstring."""
    with conn.cursor() as cur:
        cur.execute("SELECT specs FROM erp.components WHERE id = %s", (component_id,))
        specs = cur.fetchone()[0] or {}

    out: Dict = {}
    if specs.get("footprint_id"):
        out["footprint_id"] = specs["footprint_id"]
    if specs.get("pinout_family"):
        out["pinout_family"] = specs["pinout_family"]
    return out


def apply_overrides(rows: List[dict], overrides: Optional[Dict] = None) -> List[dict]:
    """
    Corrections a person made to the parsed file before running it.

    Two kinds, and both are ordinary. A quantity may be wrong because the
    document was ambiguous or because this build differs from the drawing. A
    part number may be unreadable to us because it is new -- and the person
    looking at the screen knows which catalogue part they meant, which nothing
    here could safely infer.

    Keyed by line number, because that is the one identifier the file, the
    preview and the screen all agree on.
    """
    if not overrides:
        return rows

    by_line = {}
    for key, value in overrides.items():
        try:
            by_line[int(key)] = value
        except (TypeError, ValueError):
            continue

    for row in rows:
        change = by_line.get(row.get("line_number"))
        if not isinstance(change, dict):
            continue
        if change.get("mpn"):
            row["mpn"] = str(change["mpn"]).strip()
        if change.get("quantity") is not None:
            try:
                # Zero is meaningful: it is how a line is marked do-not-populate.
                row["quantity"] = max(0, int(change["quantity"]))
            except (TypeError, ValueError):
                pass
    return rows


def ingest(conn, filepath, sku: str, name: str, build_qty: int,
           need_by: date, register: bool = True,
           overrides: Optional[Dict] = None) -> Intake:
    """Parse a BOM file, resolve it, and register the board as a product."""
    filepath = Path(filepath)
    rows = apply_overrides(parse_bom_file(filepath), overrides)
    lines = resolve_lines(conn, rows)
    counts = summarise(lines)

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO platform.build_requests
                 (source_filename, product_sku, product_name, build_qty, need_by,
                  lines_total, lines_resolved, lines_unknown)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (filepath.name, sku, name, build_qty, need_by,
             counts["total"], counts["total"] - counts[UNKNOWN], counts[UNKNOWN]),
        )
        request_id = cur.fetchone()[0]

        for line in lines:
            cur.execute(
                """INSERT INTO platform.build_request_lines
                     (request_id, line_number, reference_designator, mpn_raw,
                      description, quantity_per_board, component_id, resolution, note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (request_id, line.line_number, line.reference_designator,
                 line.mpn_raw, line.description, line.quantity_per_board,
                 line.component_id, line.resolution, line.note),
            )
    conn.commit()

    intake = Intake(request_id=request_id, filename=filepath.name, sku=sku,
                    name=name, build_qty=build_qty, need_by=need_by, lines=lines)

    if register:
        _register_product(conn, intake)

    return intake


def _register_product(conn, intake: Intake) -> None:
    """
    Write the board into erp.products and erp.bom.

    Unknown lines are NOT written: erp.bom has a foreign key to a real component,
    and inventing a placeholder row would put a part we know nothing about into
    the catalogue where agent 4 would then try to find substitutes for it. The
    board is registered with the lines we can stand behind, and the unknowns stay
    visible on the build request.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM erp.products WHERE sku = %s", (intake.sku,))
        row = cur.fetchone()

        if row:
            product_id = row[0]
            cur.execute("DELETE FROM erp.bom WHERE product_id = %s", (product_id,))
        else:
            product_id = _next_id(conn, "erp.products")
            cur.execute(
                """INSERT INTO erp.products (id, sku, name, family, description, active)
                   VALUES (%s,%s,%s,%s,%s,TRUE)""",
                (product_id, intake.sku, intake.name, "New Product Introduction",
                 f"Registered from {intake.filename}"),
            )

        for line in intake.resolved:
            cur.execute(
                """INSERT INTO erp.bom
                     (product_id, component_id, qty_per_unit, reference_designators,
                      is_critical, design_constraints)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (product_id, component_id) DO UPDATE SET
                     qty_per_unit = erp.bom.qty_per_unit + EXCLUDED.qty_per_unit""",
                (product_id, line.component_id, line.quantity_per_board,
                 line.reference_designator,
                 line.category in CRITICAL_CATEGORIES,
                 Jsonb(_derive_constraints(conn, line.component_id))),
            )

        status = "BLOCKED" if intake.unknown else "REGISTERED"
        cur.execute(
            "UPDATE platform.build_requests SET product_id = %s, status = %s WHERE id = %s",
            (product_id, status, intake.request_id),
        )
    conn.commit()

    intake.product_id = product_id
    intake.status = "BLOCKED" if intake.unknown else "REGISTERED"
