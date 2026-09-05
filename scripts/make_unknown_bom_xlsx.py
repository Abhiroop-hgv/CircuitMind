"""
A BOM of parts we do not stock, for exercising the resolution path.

The other sample resolves cleanly and goes straight to buildability. This one
is the opposite case and the more interesting demo: a customer sends a board
built from parts that are not in our catalogue at all.

What should happen, and what this file is built to show:

  1. Intake reports them as unknown. It does not guess -- two part numbers can
     differ by one character and by half the memory.
  2. Each unknown line is ranked against the catalogue, and the screen offers
     the candidates.
  3. A person picks the part they meant. The line resolves.
  4. From there it is the ordinary flow: buildability, shortfall, alternates,
     supplier scoring, approval.

The part numbers here are real devices from real manufacturers, chosen because
each has a genuine functional counterpart in our catalogue -- an ST MCU for an
ST MCU, an NXP CAN transceiver for a TI one. The descriptions are written the
way a datasheet writes them, because ranking is on shared vocabulary: a line
described as "3.3 V CAN transceiver, SOIC-8" is what makes our CAN transceivers
rank above our flash.

Four catalogue parts are included as well, STM32F407VGT6 among them. Without a
part we actually hold and are short of, the run would stop at "everything is
covered" and never reach substitution.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from db.connection import connect

ASSEMBLY = "SD-400-01"
REV = "A"
TITLE = "Sensor Drive Controller, 24 V"
COMPANY = "Kestrel Electronics Pvt Ltd"
ECO = "ECO-2026-0512"
RELEASED = "2026-09-05"

# refs, mpn, qty, manufacturer, description, package
# Parts marked NEW are deliberately absent from erp.components.
LINES = [
    ("U1", "STM32F407VGT6", 1, None, None, None),                       # held, and short
    ("U2", "STM32F446RET6", 1, "STMicroelectronics",
     "Cortex-M4F MCU, 180 MHz, 512 kB flash, LQFP-64", "LQFP-64"),      # NEW
    ("U3", "TJA1051T/3", 1, "NXP Semiconductors",
     "3.3 V CAN transceiver, 5 Mbps, SOIC-8", "SOIC-8"),                # NEW
    ("U4", "LD1117S33TR", 1, "STMicroelectronics",
     "1 A LDO, fixed 3.3 V, SOT-223", "SOT-223"),                       # NEW
    ("U5", "MT25QL128ABA1ESE-0SIT", 1, "Micron",
     "128 Mbit SPI NOR flash, SOIC-8 208 mil", "SOIC-8 208mil"),        # NEW
    ("U6", "DP83848CVV", 1, "Texas Instruments",
     "10/100 Ethernet PHY with RMII, LQFP-48", "LQFP-48"),              # NEW
    ("Q1-Q4", "IRFB4115PBF", 4, "Infineon",
     "N-channel MOSFET 150 V 104 A, TO-220AB", "TO-220AB"),             # NEW
    ("D1", "PESD1CAN", 2, "Nexperia",
     "Dual-line CAN bus ESD protection, SOT-23", "SOT-23"),             # NEW
    ("C1-C24", "C0603C104K5RACTU", 24, "Kemet",
     "100 nF 50 V X7R 10% 0603", "0603"),                               # NEW
    ("C25-C30", "GRM21BR61E106KA73L", 6, None, None, None),             # held
    ("R1-R12", "ERJ-3EKF1002V", 12, "Panasonic",
     "10 kohm 1% 0.1 W 0603", "0603"),                                  # NEW
    ("R13-R16", "RC0603FR-07100RL", 4, None, None, None),               # held
    ("L1", "SRN6045TA-100M", 1, None, None, None),                      # held
    ("Y1", "ECS-250-18-30B-CKM", 1, "ECS Inc",
     "25 MHz crystal, 18 pF, 20 ppm, SMD 3225", "SMD-3225"),            # NEW
]

HEADERS = ["Item", "Ref Des", "Qty", "Manufacturer", "Manufacturer P/N",
           "Description", "Package", "RoHS"]
WIDTHS = [6, 13, 6, 24, 26, 46, 17, 7]

INK = "20262F"
HEAD_BG = "E8ECF2"
ZEBRA = "F6F8FB"


def main() -> int:
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT mpn, manufacturer, description,
                              COALESCE(specs->>'package', '')
                         FROM erp.components""")
        cat = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"

    thin = Side(style="thin", color="C8CEDA")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws["A1"] = COMPANY
    ws["A1"].font = Font(bold=True, size=13, color=INK)
    ws["A2"] = TITLE
    ws["A2"].font = Font(size=10, color=INK)
    ws["A3"] = (f"Assembly P/N: {ASSEMBLY}    Revision: {REV}    "
                f"Released: {RELEASED}    Change ref: {ECO}")
    ws["A3"].font = Font(size=9, color="6E7A8C")
    ws["A4"] = ("Prepared: A. Menon, Hardware Engineering    Checked: S. Iyer, NPI    "
                "Approved: M. Prasad, Engineering Manager")
    ws["A4"].font = Font(size=9, color="6E7A8C")

    HEADER_ROW = 6
    for col, (name, width) in enumerate(zip(HEADERS, WIDTHS), start=1):
        cell = ws.cell(row=HEADER_ROW, column=col, value=name)
        cell.font = Font(bold=True, size=9, color=INK)
        cell.fill = PatternFill("solid", fgColor=HEAD_BG)
        cell.border = box
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width

    new_parts = 0
    for i, (refs, mpn, qty, mfr, desc, pkg) in enumerate(LINES, start=1):
        if mpn in cat:
            mfr, desc, pkg = cat[mpn]
        else:
            new_parts += 1
        row = HEADER_ROW + i
        for col, value in enumerate([i, refs, qty, mfr, mpn, desc, pkg, "Yes"], start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = Font(size=9, color=INK)
            cell.border = box
            if i % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=ZEBRA)

    notes_at = HEADER_ROW + len(LINES) + 2
    ws.cell(row=notes_at, column=1, value="Notes").font = Font(bold=True, size=9.5)
    for n, note in enumerate([
        "1. This assembly is a new introduction. Several parts are not yet on the "
        "approved parts list.",
        "2. Procurement to confirm equivalents for any part without an internal "
        "record before the first build.",
        "3. All parts RoHS 3 (EU 2015/863) compliant.",
        f"4. Total line items {len(LINES)}. "
        f"Placements per assembly {sum(l[2] for l in LINES)}.",
    ], start=1):
        ws.cell(row=notes_at + n, column=1, value=note).font = Font(size=8.5,
                                                                    color="6E7A8C")

    ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)

    out = Path(__file__).resolve().parents[1] / "samples" / f"BOM-{ASSEMBLY}-{REV}.xlsx"
    out.parent.mkdir(exist_ok=True)
    wb.save(out)

    print(f"  wrote {out}")
    print(f"  {len(LINES)} line items, {new_parts} not in the catalogue, "
          f"{len(LINES) - new_parts} held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
