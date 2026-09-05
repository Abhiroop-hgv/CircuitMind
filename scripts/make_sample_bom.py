"""
Build a sample BOM PDF laid out the way a contract manufacturer expects one.

The first version was a five-column table, which parsed cleanly and proved very
little. A real assembly BOM is a controlled document: a title block with an
assembly number and revision, an approvals row, a change reference, per-line
lifecycle and compliance status, DNP lines that must not be purchased, and
approved alternates. Those are the parts that break a parser, so those are the
parts worth having in a fixture -- and they did break it, five ways.

Columns follow the EMS-ready set assembly houses ask for. Sources:

    https://www.anzer-usa.com/resources/electronic-design-bom/
    https://jlcpcb.com/help/article/bill-of-materials-for-pcb-assembly
    https://www.pcbway.com/blog/PCB_Assembly/How_to_Build_a_BOM__Bill_Of_Materials_.html

Data comes from erp.components, so lifecycle and package agree with the database
rather than asserting something it contradicts. Two part numbers are absent from
the catalogue on purpose: intake must report them as unknown rather than guess.
Two lines are DNP: on the drawing, not to be bought.

Kestrel Electronics is a fictional company invented for this fixture. The one
real external reference is the TI datasheet cited in note 7, which is a genuine
public document (SLOS068AB) covering the LM358B on line 21 -- cited, not
reproduced or altered.

A note on the styling: the fills and rules are not decoration. Text extraction
ignores them, so the document can look like it came out of a PLM system while
the parser still reads the same header row and the same columns.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from db.connection import connect

COMPANY = "Kestrel Electronics Pvt Ltd"
SITE = "Plant 2, Hosur"
ASSEMBLY = "MC-4000-01"
REV = "B"
TITLE = "Motor Controller, 3-Phase, 48 V"
DOCNO = f"BOM-{ASSEMBLY}-{REV}"
ECO = "ECO-2026-0447"
RELEASED = "2026-09-01"

INK = (32, 38, 48)
RULE = (176, 184, 196)
HEAD_FILL = (232, 236, 242)
ZEBRA = (246, 248, 251)
MUTED = (122, 132, 148)

# refs, mpn, qty, dnp, approved alternate
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
    # Shown on the drawing, not purchased. A build that counts these is wrong.
    ("R27-R28", "RC0603FR-0710KL",      2,  True,  ""),
    ("C43",     "GRM21BR61E106KA73L",   1,  True,  ""),
    # Absent from the catalogue on purpose.
    ("U7",      "MCP2515-I/SO",         1,  False, ""),
    ("U8",      "LM358BDR",             1,  False, ""),
]

# Parts we do not hold. The customer's own data stands for these.
OUTSIDE = {
    "MCP2515-I/SO": ("Microchip", "Stand-alone CAN controller with SPI",
                     "SOIC-18", "NRND"),
    "LM358BDR":     ("Texas Instruments", "Dual operational amplifier",
                     "SOIC-8", "ACTIVE"),
}

COLS = [
    ("Item", 9), ("Ref Des", 28), ("Qty", 9), ("Manufacturer", 30),
    ("Manufacturer P/N", 36), ("Description", 54), ("Package", 19),
    ("Lifecycle", 15), ("RoHS", 11), ("DNP", 9), ("Approved Alternate", 34),
]

NOTES = [
    "1. Lines marked DNP are shown on the assembly drawing and shall not be "
    "purchased or placed.",
    "2. Approved alternates are drop-in equivalents released by engineering. Any "
    "other substitution requires an approved deviation.",
    "3. All parts RoHS 3 (EU 2015/863) compliant. Certificates of conformance "
    "required at first article.",
    "4. U1 and U6 are MSL 3: bake per J-STD-033 if floor life is exceeded. ESD "
    "sensitive, handle per ANSI/ESD S20.20.",
    "5. U1 is programmed post-assembly with firmware MC4000-FW rev 2.4.",
    "6. U7 is NRND. Engineering to confirm a second source before the next build "
    "release.",
    "7. U8 LM358BDR: refer to the supplier datasheet issued with this release, "
    "Texas Instruments SLOS068AB Rev AB.",
]


def catalogue():
    """Manufacturer, description, package and lifecycle, from the ERP mirror."""
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT mpn, manufacturer, description,
                              COALESCE(specs->>'package', ''), lifecycle
                         FROM erp.components""")
        rows = {r[0]: (r[1], r[2], r[3], r[4]) for r in cur.fetchall()}
    conn.close()
    return rows


def fit(text: str, mm: float, pt: float = 6.5) -> str:
    """
    Trim to what the cell can hold.

    Courier is 0.6 em wide, so a character is 0.6 * pt / 2.835 mm. Text that
    overflows does not wrap here, it collides -- and PDF extraction then reports
    the collision as a single token, which is how "SystemsAMS1117-3.3" got into
    an earlier fixture.
    """
    per_char = 0.6 * pt / 2.835
    return text[: max(1, int(mm / per_char) - 1)]


class Sheet(FPDF):
    def header(self) -> None:
        self.set_text_color(*INK)

        self.set_font("Helvetica", "B", 13)
        self.cell(120, 6, COMPANY, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(60, 6, SITE, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_text_color(*INK)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 6, "BILL OF MATERIALS", align="R",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_draw_color(*RULE)
        self.set_line_width(0.5)
        y = self.get_y() + 1
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(3)

        # Title block, as a bordered grid the way a controlled document prints.
        fields = [
            ("Assembly P/N", ASSEMBLY, 46), ("Description", TITLE, 74),
            ("Revision", REV, 22), ("Document", DOCNO, 44),
            ("Released", RELEASED, 32), ("Change ref", ECO, 40),
        ]
        self.set_line_width(0.2)
        self.set_font("Helvetica", "", 6)
        for name, _, w in fields:
            self.set_text_color(*MUTED)
            self.cell(w, 3.6, "  " + name.upper(), new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln(3.6)
        self.set_font("Helvetica", "B", 7.5)
        self.set_text_color(*INK)
        for _, value, w in fields:
            self.cell(w, 5, "  " + value, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln(5)

        self.set_font("Helvetica", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5,
                  "  Prepared: R. Nair, Hardware Engineering        "
                  "Checked: S. Iyer, NPI        "
                  "Approved: M. Prasad, Engineering Manager        "
                  "Classification: Internal",
                  border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

        self.set_font("Courier", "B", 6.5)
        self.set_text_color(*INK)
        self.set_fill_color(*HEAD_FILL)
        for name, w in COLS:
            self.cell(w, 5, " " + name, border=1, fill=True,
                      new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln(5)
        self.set_font("Courier", "", 6.5)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1)
        self.set_font("Helvetica", "", 6)
        self.set_text_color(*MUTED)
        self.cell(90, 4, f"{DOCNO}   {ECO}", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.cell(90, 4, "Uncontrolled when printed", align="C",
                  new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.cell(0, 4, f"Page {self.page_no()}", align="R")


def main() -> int:
    cat = catalogue()

    pdf = Sheet(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    fitted = 0
    for i, (refs, mpn, qty, dnp, alt) in enumerate(LINES, start=1):
        mfr, desc, pkg, life = cat.get(mpn, OUTSIDE.get(mpn, ("", "", "", "")))
        if not dnp:
            fitted += qty

        pdf.set_fill_color(*(ZEBRA if i % 2 == 0 else (255, 255, 255)))
        pdf.set_text_color(*(MUTED if dnp else INK))
        cells = [
            str(i), refs, str(qty), fit(mfr, 30), mpn, fit(desc, 54),
            fit(pkg, 19), life, "Yes", "DNP" if dnp else "", alt,
        ]
        for (_, w), text in zip(COLS, cells):
            pdf.cell(w, 4.4, " " + text, border="LR", fill=True,
                     new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.ln(4.4)

    # close the table
    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + sum(w for _, w in COLS),
             pdf.get_y())
    pdf.ln(4)

    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 5, "Notes", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 7)
    for note in NOTES + [
        f"8. Total line items {len(LINES)}. Placements per assembly {fitted}, "
        f"excluding DNP.",
    ]:
        pdf.multi_cell(0, 3.9, note, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 5, "Revision history", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    hist_cols = [("Rev", 14), ("Date", 26), ("Change ref", 34), ("Description", 180)]
    pdf.set_font("Courier", "B", 6.5)
    pdf.set_fill_color(*HEAD_FILL)
    for name, w in hist_cols:
        pdf.cell(w, 4.6, " " + name, border=1, fill=True,
                 new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.ln(4.6)

    pdf.set_font("Courier", "", 6.5)
    for rev, date, ref, what in [
        ("A", "2026-06-14", "ECO-2026-0301", "Initial release"),
        ("B", "2026-09-01", ECO,
         "Added CAN controller U7 and dual op-amp U8. Decoupling increased to 32 "
         "places. R27-R28 and C43 changed to DNP."),
    ]:
        for (_, w), text in zip(hist_cols, [rev, date, ref, what]):
            pdf.cell(w, 4.4, " " + fit(text, w), border=1,
                     new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.ln(4.4)

    out = Path(__file__).resolve().parents[1] / "samples" / f"{DOCNO}.pdf"
    out.parent.mkdir(exist_ok=True)
    pdf.output(str(out))

    print(f"  wrote {out}")
    print(f"  {len(LINES)} line items, {fitted} placements fitted, "
          f"{sum(1 for l in LINES if l[3])} DNP, "
          f"{sum(1 for l in LINES if l[1] not in cat)} outside the catalogue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
