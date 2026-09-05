"""
Build a spreadsheet BOM from the catalogue, for testing the intake path.

Two properties make this file actually exercisable, and both are deliberate:

  every part resolves    The dashboard disables "Register board & check
                         buildability" while any line is unknown, so a BOM with
                         invented part numbers cannot be run at all. Every MPN
                         here comes from erp.components.

  it blocks             The board includes STM32F407VGT6, the part with a live
                         shortfall. A BOM that is fully buildable stops at "all
                         covered" and never reaches substitution -- so it would
                         demonstrate nothing about alternates or constraints.
                         This one blocks, which is the interesting path.

Everything except the assembly identity is read from the database, so the
descriptions, packages and manufacturers match what the resolver will find.
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

ASSEMBLY = "MC-4100-01"
REV = "A"
TITLE = "Motor Controller, 3-Phase, 48 V, Rev A"
COMPANY = "Kestrel Electronics Pvt Ltd"
ECO = "ECO-2026-0501"
RELEASED = "2026-09-05"

# refs, mpn, qty, dnp, approved alternate. MPNs are all in the catalogue.
LINES = [
    ("U1",      "STM32F407VGT6",        1,  False, "STM32F429VGT6"),
    ("U2",      "DRV8301DCAR",          1,  False, ""),
    ("Q1-Q6",   "IRFB4110PBF",          6,  False, ""),
    ("U3",      "TPS54331DDAR",         1,  False, ""),
    ("U4",      "AMS1117-3.3",          1,  False, "NCP1117ST33T3G"),
    ("U5",      "SN65HVD230DR",         1,  False, "TCAN332DR"),
    ("U6",      "W25Q128JVSIQ",         1,  False, "MX25L12835FM2I-10G"),
    ("Y1",      "ABM8-25.000MHZ-D2Y-T", 1,  False, ""),
    ("D1",      "USBLC6-2SC6",          1,  False, ""),
    ("C1-C32",  "GRM188R71H104KA93D",  32,  False, "CL10B104KB8NNNC"),
    ("C33-C42", "GRM21BR61E106KA73L",  10,  False, ""),
    ("R1-R16",  "RC0603FR-0710KL",     16,  False, ""),
    ("R17-R22", "RC0603FR-07100RL",     6,  False, ""),
    ("R23-R26", "RC0603FR-074K7L",      4,  False, ""),
    ("L1-L2",   "SRN6045TA-100M",       2,  False, ""),
    ("J1-J2",   "43045-0400",           2,  False, ""),
    ("D2-D3",   "SMAJ33A",              2,  False, ""),
    ("R27-R28", "RC0603FR-0710KL",      2,  True,  ""),   # fitted, not bought
    ("C43",     "GRM21BR61E106KA73L",   1,  True,  ""),
]

HEADERS = ["Item", "Ref Des", "Qty", "Manufacturer", "Manufacturer P/N",
           "Description", "Package", "Lifecycle", "RoHS", "DNP",
           "Approved Alternate"]
WIDTHS = [6, 14, 6, 26, 24, 46, 18, 11, 7, 6, 22]

INK = "20262F"
HEAD_BG = "E8ECF2"
ZEBRA = "F6F8FB"


def catalogue(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT mpn, manufacturer, description,
                              COALESCE(specs->>'package', ''), lifecycle
                         FROM erp.components""")
        return {r[0]: (r[1], r[2], r[3], r[4]) for r in cur.fetchall()}


def main() -> int:
    conn = connect()
    cat = catalogue(conn)
    conn.close()

    missing = [mpn for _, mpn, *_ in LINES if mpn not in cat]
    if missing:
        # Refuse rather than ship a file that cannot be run.
        print("  these part numbers are not in the catalogue:", missing)
        return 1

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
    ws["A4"] = ("Prepared: R. Nair, Hardware Engineering    Checked: S. Iyer, NPI    "
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

    fitted = 0
    for i, (refs, mpn, qty, dnp, alt) in enumerate(LINES, start=1):
        mfr, desc, pkg, life = cat[mpn]
        if not dnp:
            fitted += qty
        values = [i, refs, qty, mfr, mpn, desc, pkg, life, "Yes",
                  "DNP" if dnp else "", alt]
        row = HEADER_ROW + i
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = Font(size=9, color="8A93A3" if dnp else INK)
            cell.border = box
            if i % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=ZEBRA)

    notes_at = HEADER_ROW + len(LINES) + 2
    ws.cell(row=notes_at, column=1, value="Notes").font = Font(bold=True, size=9.5)
    for n, note in enumerate([
        "1. Lines marked DNP are shown on the assembly drawing and shall not be purchased.",
        "2. Approved alternates are drop-in equivalents released by engineering.",
        "3. All parts RoHS 3 (EU 2015/863) compliant.",
        f"4. Total line items {len(LINES)}. Placements per assembly {fitted}, excluding DNP.",
    ], start=1):
        ws.cell(row=notes_at + n, column=1, value=note).font = Font(size=8.5,
                                                                    color="6E7A8C")

    ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)

    out = Path(__file__).resolve().parents[1] / "samples" / f"BOM-{ASSEMBLY}-{REV}.xlsx"
    out.parent.mkdir(exist_ok=True)
    wb.save(out)

    print(f"  wrote {out}")
    print(f"  {len(LINES)} line items, {fitted} placements fitted, "
          f"{sum(1 for l in LINES if l[3])} DNP, 0 unknown")
    print(f"  includes STM32F407VGT6, so the build check will block and the "
          f"substitution path runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
