# -*- coding: utf-8 -*-
"""
Generate a realistic BOM spreadsheet that is deliberately ~70% resolvable.

The point of this fixture is the other 30%. A BOM where every line matches is a
demo of nothing -- real bills of materials arrive with passives, connectors and
mechanical parts that were never in the component catalogue, and the interesting
question is what the system does with those. It should rank them for a person,
not guess.

    python scripts/make_mixed_bom_xlsx.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from db.connection import connect

OUT = Path(__file__).resolve().parents[1] / "samples" / "MC-3000_RevD_BOM.xlsx"

# Parts that genuinely are not in the catalogue: passives, connectors, crystals,
# mechanical. Every one is a real orderable part number -- they are "unknown" to
# us, not fictional.
UNKNOWN = [
    ("C1,C2,C3,C4", 4, "C0603C104K5RACTU", "KEMET",
     "Capacitor, 100 nF, 50 V, X7R, 0603", "0603"),
    ("C11,C12", 2, "EEE-FK1V101P", "Panasonic",
     "Capacitor, aluminium electrolytic, 100 uF, 35 V", "SMD-D"),
    ("R1,R2,R3,R4,R5,R6", 6, "CRCW060310K0FKEA", "Vishay",
     "Resistor, 10 kOhm, 1%, 1/10 W, 0603", "0603"),
    ("R20,R21", 2, "ERJ-3EKF4990V", "Panasonic",
     "Resistor, 499 Ohm, 1%, 1/10 W, 0603", "0603"),
    ("L1", 1, "744314650", "Wurth Elektronik",
     "Inductor, power, 6.8 uH, 5.5 A, shielded", "WE-PD"),
    ("Y1", 1, "ABM8-8.000MHZ-B2-T", "Abracon",
     "Crystal, 8.000 MHz, 18 pF, 20 ppm", "SMD-3225"),
    ("J1", 1, "1-1734248-4", "TE Connectivity",
     "Connector, header, 4-pos, 2.54 mm, vertical", "THT"),
    ("J4", 1, "DF13-10P-1.25V", "Hirose",
     "Connector, wire-to-board, 10-pos, 1.25 mm", "SMD"),
    ("F1", 1, "0685P2000-01", "Bel Fuse",
     "Fuse, PTC resettable, 2 A, 30 V", "1812"),
    ("D9", 1, "SMBJ33CA", "Littelfuse",
     "TVS diode, bidirectional, 33 V, 600 W", "SMB"),
    ("TP1,TP2,TP3", 3, "5015", "Keystone",
     "Test point, PCB, red, through-hole", "THT"),
    ("MH1,MH2,MH3,MH4", 4, "9774050243R", "Wurth Elektronik",
     "Standoff, M2.5 x 5 mm, brass", "MECH"),
]

# Two lines are fitted on the board layout but deliberately not populated on
# this revision. They must survive the parser as quantity 0, not become 1.
DNP_ROWS = {"R20,R21", "TP1,TP2,TP3"}

HEAD = PatternFill("solid", fgColor="1E3A54")
ALT = PatternFill("solid", fgColor="F7F1E6")
THIN = Side(style="thin", color="D9D9D9")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def catalogue_rows(limit: int) -> list[tuple]:
    """Real parts, straight out of the catalogue, with plausible designators."""
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT mpn, manufacturer, description, category
                         FROM erp.components ORDER BY id LIMIT %s""", (limit,))
        rows = cur.fetchall()
    conn.close()

    prefix = {"MCU": "U", "GATE_DRIVER": "U", "MOSFET": "Q", "ETHERNET_PHY": "U",
              "REGULATOR": "VR", "SENSOR": "U", "MEMORY": "U", "CONNECTOR": "J"}
    out, seen = [], {}
    for mpn, mfr, desc, cat in rows:
        p = prefix.get(cat, "U")
        seen[p] = seen.get(p, 0) + 1
        qty = 1 if p in ("U", "VR") else 2
        out.append((f"{p}{seen[p]}", qty, mpn, mfr, desc, ""))
    return out


def main() -> int:
    real = catalogue_rows(28)
    rows = []
    # interleave so the unknowns are not all clustered at the bottom
    r_i = u_i = 0
    while r_i < len(real) or u_i < len(UNKNOWN):
        for _ in range(3):
            if r_i < len(real):
                rows.append(real[r_i]); r_i += 1
        if u_i < len(UNKNOWN):
            rows.append(UNKNOWN[u_i]); u_i += 1

    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"

    ws["A1"] = "Kestrel Electronics Pvt Ltd"
    ws["A1"].font = Font(size=14, bold=True, color="1E3A54")
    ws["A2"] = "Assembly: MC-3000 Motor Controller Board"
    ws["A3"] = "Revision: D          Date: 2026-09-06          Sheet 1 of 1"
    for r in ("A2", "A3"):
        ws[r].font = Font(size=10, color="6B6B63")

    head = ["Item", "Reference", "Qty", "Manufacturer Part Number",
            "Manufacturer", "Description", "Package", "DNP"]
    ws.append([])
    ws.append(head)
    hr = ws.max_row
    for c in range(1, len(head) + 1):
        cell = ws.cell(hr, c)
        cell.fill, cell.border = HEAD, BOX
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for i, (ref, qty, mpn, mfr, desc, pkg) in enumerate(rows, 1):
        dnp = ref in DNP_ROWS
        ws.append([i, ref, 0 if dnp else qty, mpn, mfr, desc, pkg,
                   "DNP" if dnp else ""])
        for c in range(1, len(head) + 1):
            cell = ws.cell(ws.max_row, c)
            cell.border = BOX
            cell.font = Font(size=10)
            if i % 2 == 0:
                cell.fill = ALT
        ws.cell(ws.max_row, 3).alignment = Alignment(horizontal="center")
        ws.cell(ws.max_row, 8).alignment = Alignment(horizontal="center")

    for col, w in zip("ABCDEFGH", (6, 20, 6, 26, 20, 58, 12, 7)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = ws.cell(hr + 1, 1)

    OUT.parent.mkdir(exist_ok=True)
    wb.save(OUT)

    known = sum(1 for r in rows if r not in UNKNOWN)
    print(f"  wrote {OUT}")
    print(f"  {len(rows)} lines -- {known} in catalogue "
          f"({known / len(rows):.0%}), {len(UNKNOWN)} not")
    print(f"  {len(DNP_ROWS)} do-not-populate lines at quantity 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
