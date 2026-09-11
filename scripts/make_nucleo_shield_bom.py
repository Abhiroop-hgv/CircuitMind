"""
Build a demo document: a board-overview brief plus a bill of materials, for a
motor-control shield that plugs onto a NUCLEO-G474RE.

WHY THIS EXISTS
----------------
A real STMicroelectronics document for the Nucleo-64 family (their "Data
Brief", DB2196) was downloaded for a demo and turned out to carry no bill of
materials at all -- it is a family-wide overview across 30+ board variants,
and says outright that schematics, EDA files and the BOM are separate
downloads from the product page. There was nothing in it to edit into a
working demo fixture.

Rather than graft invented content onto a real STMicroelectronics
publication, this generates an original document from scratch: a shield/
carrier board that plugs onto the Nucleo-G474RE's Arduino Uno V3 + ST morpho
headers and carries its OWN components, in the CircuitMind style already
established by make_sample_bom.py (fictional company, controlled-document
title block, the works). The overview pages are written fresh -- the general
facts referenced (ST-LINK on-board, Arduino Uno V3 + ST morpho headers,
STM32CubeIDE support) are the same widely-published facts any Nucleo-64
product page states, not text lifted from ST's document. NUCLEO-G474RE is
named only as the compatible host module, the way any third-party shield
documents which board it plugs into.

The BOM is real: every line's manufacturer, description, package and
lifecycle comes from erp.components (see catalogue()), the same source
make_sample_bom.py reads from. The board's own theme -- three-phase gate
driver, MOSFETs, CAN, buck and LDO rails -- was picked because it is what the
seeded catalogue actually stocks, not the other way around. Two part numbers
are absent from the catalogue on purpose, and one line is DNP, for the same
reasons make_sample_bom.py's are: intake must report an unmatched line as
unknown rather than guess, and a DNP line must count as zero rather than one.
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
ASSEMBLY = "KE-G474-SHIELD"
REV = "A"
TITLE = "3-Phase Motor-Control Shield for NUCLEO-G474RE"
DOCNO = f"BOM-{ASSEMBLY}-{REV}"
ECO = "ECO-2026-0512"
RELEASED = "2026-09-11"
HOST_BOARD = "NUCLEO-G474RE"
HOST_MCU = "STM32G474RET6"

INK = (32, 38, 48)
RULE = (176, 184, 196)
HEAD_FILL = (232, 236, 242)
ZEBRA = (246, 248, 251)
MUTED = (122, 132, 148)
ACCENT = (26, 92, 168)

# refs, mpn, qty, dnp, approved alternate
LINES = [
    ("U1",      "DRV8301DCAR",          1,  False, ""),
    ("Q1-Q6",   "IRFB4110PBF",          6,  False, ""),
    ("U2",      "TPS54331DDAR",         1,  False, ""),
    ("U3",      "AMS1117-3.3",          1,  False, "NCP1117ST33T3G"),
    ("U4",      "TCAN332DR",            1,  False, "SN65HVD230DR"),
    ("U5",      "MCP2551-I/SN",         1,  False, ""),
    ("U6",      "W25Q128JVSIQ",         1,  False, "MX25L12835FM2I-10G"),
    ("U7",      "USBLC6-2SC6",          1,  False, ""),
    ("U8",      "KSZ8081RNBIA-TR",      1,  False, "LAN8720AI-CP-TR"),
    ("Y1",      "ABM8-25.000MHZ-D2Y-T", 1,  False, ""),
    ("L1",      "SRN6045TA-100M",       1,  False, ""),
    ("D1-D2",   "SMAJ33A",              2,  False, ""),
    ("C1-C16",  "GRM188R71H104KA93D",  16,  False, "CL10B104KB8NNNC"),
    ("C17-C24", "GRM21BR61E106KA73L",   8,  False, ""),
    ("R1-R10",  "RC0603FR-0710KL",     10,  False, ""),
    ("R11-R14", "RC0603FR-07100RL",     4,  False, ""),
    ("R15-R18", "RC0603FR-074K7L",      4,  False, ""),
    ("J1-J2",   "43045-0400",           2,  False, ""),
    # Shown on the drawing, not purchased -- the Wi-Fi option is unpopulated
    # on the standard build.
    ("U9",      "ESP32-WROOM-32E-N8",   1,  True,  ""),
    # Absent from the catalogue on purpose: intake must flag these, not guess.
    ("U10",     "MCP2515-I/SO",         1,  False, ""),
    ("U11",     "LM358BDR",             1,  False, ""),
]

OUTSIDE = {
    "MCP2515-I/SO": ("Microchip", "Stand-alone CAN controller with SPI",
                     "SOIC-18", "NRND"),
    "LM358BDR":     ("Texas Instruments", "Dual operational amplifier",
                     "SOIC-8", "ACTIVE"),
}

COLS = [
    ("Item", 9), ("Ref Des", 26), ("Qty", 9), ("Manufacturer", 30),
    ("Manufacturer P/N", 36), ("Description", 52), ("Package", 19),
    ("Lifecycle", 15), ("RoHS", 11), ("DNP", 9), ("Approved Alternate", 36),
]

NOTES = [
    "1. U9 is shown on the assembly drawing but is DNP on the standard build; "
    "populate only for the Wi-Fi telemetry variant.",
    "2. Approved alternates are drop-in equivalents released by engineering. "
    "Any other substitution requires an approved deviation.",
    "3. All parts RoHS 3 (EU 2015/863) compliant. Certificates of conformance "
    "required at first article.",
    "4. U1 and U6 are MSL 3: bake per J-STD-033 if floor life is exceeded. ESD "
    "sensitive, handle per ANSI/ESD S20.20.",
    "5. This shield supplies its own logic and gate-drive rails (U2, U3) and "
    "does not draw motor-side current from the host module's regulators.",
    "6. U10 is NRND. Engineering to confirm a second source before the next "
    "build release.",
    "7. Mates to the host module's Arduino Uno V3 footprint. Verify J1/J2 "
    "keying before power-up -- reversed mating exposes host module I/O to "
    "the DC bus.",
]


# ---------------------------------------------------------------------------
# Front matter: an original board-overview brief, NOT text from ST's Data
# Brief for the Nucleo-64 family -- see this module's docstring.
# ---------------------------------------------------------------------------

FEATURES = [
    "Plugs directly onto the Arduino Uno V3 and ST morpho headers of a "
    f"{HOST_BOARD} (host module supplied separately; target device "
    f"{HOST_MCU}).",
    "Three-phase gate driver with integrated current-shunt amplifiers, "
    "sized for field-oriented control loops running on the host module's "
    "HRTIM and comparator peripherals.",
    "Six N-channel power MOSFETs, 100 V / 180 A per device, two per phase leg.",
    "Isolated CAN transceiver for multi-axis or vehicle-network integration, "
    "independent of the host module's own USB/UART debug path.",
    "On-board 3.3 V logic rail and a separate buck-regulated gate-drive "
    "rail, so the shield never loads the host module's own supply.",
    "ESD-protected auxiliary USB port and an Ethernet PHY footprint for "
    "networked deployments.",
    "Screw-terminal DC-bus and motor-phase connections, keyed against "
    "reversed mating with the host header set.",
    "Optional Wi-Fi telemetry module footprint (DNP on the standard build "
    "-- see BOM note 1).",
]

DESCRIPTION = (
    f"This shield turns a {HOST_BOARD} into a self-contained three-phase "
    "motor-drive evaluation platform. The host module contributes the "
    f"{HOST_MCU} microcontroller, its ST-LINK debugger, and the timer and "
    "ADC resources the STM32 Motor Control SDK's field-oriented control "
    "examples expect; the shield contributes everything the motor itself "
    "needs -- gate drive, power switching, current sensing, and the DC-bus "
    "and phase connections -- so none of it has to be routed through, or "
    "draw current from, the host module's own circuitry.\n\n"
    "Keeping the power stage on a separate board from the microcontroller "
    "module is deliberate: a fault on the motor side (a shorted phase, a "
    "reversed DC-bus connection) stays confined to the shield's own "
    "regulators and MOSFETs rather than reaching back into the host "
    "module's supply rails or debug interface."
)

HOST_FACTS = [
    ("Host module", HOST_BOARD),
    ("Target device", HOST_MCU),
    ("Package", "LQFP64"),
    ("On-board debugger", "STLINK-V3E"),
    ("High-speed external oscillator", "24 MHz"),
    ("Expansion connectors", "Arduino Uno V3 + ST morpho"),
    ("Debug connector", "MIPI-10"),
]

POWER_ARCH = (
    "The shield derives its own 3.3 V logic supply from U3, an LDO fed from "
    "the DC bus rather than from the host module's 5 V rail, so the gate "
    "driver and CAN transceiver stay powered even while the host module is "
    "connected only over USB for debugging with no DC bus present.\n\n"
    "A separate buck stage (U2) regulates the gate-drive rail the driver "
    "IC (U1) switches from, sized for the six MOSFETs' total gate charge at "
    "the shield's rated switching frequency. The two rails share a common "
    "ground with the host module across the connector pair (J1, J2), but "
    "neither supply is derived from the other."
)

DEV_ENV = [
    "STM32CubeIDE, with the STM32 Motor Control SDK's field-oriented "
    "control workbench targeting the host module's peripheral map.",
    "IAR Embedded Workbench and Keil MDK-ARM are both supported for the "
    "host module; neither toolchain needs shield-specific configuration "
    "beyond the pin assignments in the schematic.",
    "The host module's on-board ST-LINK provides programming and debug "
    "over the same USB connection used for power during bring-up (DC bus "
    "disconnected).",
]

GETTING_STARTED = [
    "Confirm the DC bus is disconnected before seating the shield on the "
    "host module's headers.",
    "Seat the shield fully on both the Arduino Uno V3 and ST morpho "
    "headers -- a partial seat on only one connector is the most common "
    "assembly fault and can expose host module I/O to gate-drive voltages.",
    "Apply DC bus power only after the host module reports a successful "
    "ST-LINK enumeration over USB.",
    "Load the Motor Control SDK workbench project for this shield's motor "
    "profile before the first spin-up; the default HRTIM configuration "
    "assumes this shield's gate-drive rail voltage, not a bare host module.",
]

ORDERING = [
    ("Order code", "KE-G474-SHIELD-A"),
    ("Compatible host module", HOST_BOARD),
    ("Also fits", "Any Nucleo-64 board sharing the Arduino Uno V3 + ST "
                  "morpho footprint and a 3.3 V I/O rail"),
    ("Not compatible with", "Nucleo-32 or Nucleo-144 board footprints"),
]

CONNECTOR_PINOUT = [
    ("J1 pin 1-2", "DC bus +, DC bus return"),
    ("J1 pin 3-8", "Motor phases A, B, C (two pins each, for crimp strain relief)"),
    ("J2 pin 1-2", "Shield 3.3 V rail out, ground (for probing only -- not a supply input)"),
    ("J2 pin 3-4", "CAN_H, CAN_L"),
    ("J2 pin 5-6", "Aux USB D+, D-"),
    ("J2 pin 7-8", "Ethernet PHY RMII reference clock, ground"),
]

TEST_POINTS = [
    "TP1 -- gate-drive rail output (U2), referenced to shield ground.",
    "TP2 -- 3.3 V logic rail output (U3).",
    "TP3-TP5 -- per-phase current-shunt amplifier outputs, direct from U1, "
    "before any host-module ADC scaling.",
    "TP6 -- CAN_H/CAN_L differential pair, for bus-loading measurements "
    "with the shield isolated from the host module's own debug session.",
]

SAFETY = [
    "The DC bus connector (J1) can carry motor-drive voltages well above "
    "the host module's own 3.3-5 V logic levels. Disconnect the DC bus "
    "before seating or removing the shield.",
    "U1, U2 and the MOSFETs (Q1-Q6) are ESD sensitive; handle per "
    "ANSI/ESD S20.20 outside of the assembled unit.",
    "All parts are RoHS 3 (EU 2015/863) and REACH compliant per the "
    "manufacturer declarations on file; see BOM note 3.",
    "This shield is an engineering evaluation aid, not a certified "
    "end product -- it carries no independent safety agency marking of "
    "its own beyond the individual components' certifications.",
]

FIRMWARE_EXAMPLES = [
    "Field-oriented control: the STM32 Motor Control SDK's FOC workbench, "
    "reconfigured for this shield's gate-drive rail and current-shunt "
    "scaling (see section 4).",
    "CAN telemetry: a minimal periodic-broadcast example over U4/U5, "
    "useful as a starting point before integrating a project-specific "
    "message set.",
    "Network bring-up: a DHCP-and-ping example exercising U8's RMII path, "
    "to confirm the Ethernet PHY footprint before building on it.",
    "None of these examples are included in this document -- they are "
    "distributed with the Motor Control SDK and referenced here for "
    "orientation only.",
]


def fit(text: str, mm: float, pt: float = 6.5) -> str:
    """Trim to what a fixed-width cell can hold without colliding text."""
    per_char = 0.6 * pt / 2.835
    return text[: max(1, int(mm / per_char) - 1)]


def catalogue():
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT mpn, manufacturer, description,
                              COALESCE(specs->>'package', ''), lifecycle
                         FROM erp.components""")
        rows = {r[0]: (r[1], r[2], r[3], r[4]) for r in cur.fetchall()}
    conn.close()
    return rows


class Doc(FPDF):
    """
    One document, two page styles: a plain masthead for the overview pages
    (portrait) and the full controlled-document title block for the BOM
    pages (landscape) -- switched with self.bom_mode before each add_page().
    """

    bom_mode = False
    show_columns = True  # False on the revision-history page -- see build_bom

    def header(self) -> None:
        self.set_text_color(*INK)
        if not self.bom_mode:
            self.set_font("Helvetica", "B", 11)
            self.cell(0, 6, COMPANY, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_font("Helvetica", "", 7.5)
            self.set_text_color(*MUTED)
            self.cell(0, 5, f"{DOCNO}    Rev {REV}    {TITLE}",
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_draw_color(*RULE)
            self.set_line_width(0.4)
            y = self.get_y() + 1.5
            self.line(self.l_margin, y, self.w - self.r_margin, y)
            self.ln(6)
            return

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

        fields = [
            ("Assembly P/N", ASSEMBLY, 46), ("Description", TITLE, 92),
            ("Revision", REV, 18), ("Document", DOCNO, 44),
            ("Released", RELEASED, 30), ("Change ref", ECO, 34),
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
            self.cell(w, 5, "  " + fit(value, w, 7.5), border=1,
                      new_x=XPos.RIGHT, new_y=YPos.TOP)
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

        if self.show_columns:
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
        self.cell(90, 4, "Internal reference document -- not an ST publication",
                  align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.cell(0, 4, f"Page {self.page_no()}", align="R")

    # -- overview-page helpers ----------------------------------------------

    def h1(self, text: str) -> None:
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(*ACCENT)
        self.cell(0, 9, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.6)
        y = self.get_y() + 1
        self.line(self.l_margin, y, self.l_margin + 28, y)
        self.ln(6)
        self.set_text_color(*INK)

    def bullets(self, items) -> None:
        self.set_font("Helvetica", "", 9.5)
        for item in items:
            self.set_text_color(*ACCENT)
            self.cell(5, 5.2, chr(149))
            self.set_text_color(*INK)
            self.multi_cell(0, 5.2, item, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(0.8)

    def para(self, text: str) -> None:
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(*INK)
        for block in text.split("\n\n"):
            self.multi_cell(0, 5.4, block, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(2.5)

    def fact_table(self, rows, label_w=55) -> None:
        self.set_font("Helvetica", "B", 9)
        for label, value in rows:
            self.set_fill_color(*HEAD_FILL)
            self.set_text_color(*INK)
            self.cell(label_w, 7, "  " + label, border=1, fill=True,
                      new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.set_font("Helvetica", "", 9)
            self.set_fill_color(255, 255, 255)
            self.multi_cell(0, 7, "  " + value, border=1,
                            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_font("Helvetica", "B", 9)
        self.ln(2)


def build_overview(pdf: Doc) -> None:
    pdf.bom_mode = False

    # Cover
    pdf.add_page()
    pdf.ln(30)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*ACCENT)
    pdf.multi_cell(0, 12, TITLE, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 8, f"Compatible host module: {HOST_BOARD}", align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(14)

    # Host-board photography is STMicroelectronics' own product photo, not
    # ours to reproduce here -- especially not on a page that disclaims any
    # ST affiliation. A captioned placeholder, the way an internal doc
    # references a third party's imagery without copying it.
    box_w, box_h = 130, 46
    box_x = (pdf.w - box_w) / 2
    box_y = pdf.get_y()
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.3)
    pdf.rect(box_x, box_y, box_w, box_h)
    pdf.set_xy(box_x, box_y + box_h / 2 - 7)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(box_w, 5, f"Host module photo: {HOST_BOARD}", align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(box_x)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.cell(box_w, 5, "refer to the product page at www.st.com", align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(box_y + box_h)
    pdf.ln(14)

    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.3)
    y = pdf.get_y()
    pdf.line(70, y, pdf.w - 70, y)
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(*INK)
    for label, value in [
        ("Document", DOCNO), ("Revision", REV), ("Released", RELEASED),
        ("Prepared by", f"{COMPANY}, {SITE}"),
    ]:
        pdf.cell(0, 6, f"{label}:  {value}", align="C",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(20)
    pdf.set_font("Helvetica", "I", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        0, 5,
        "Internal engineering reference document. NUCLEO-G474RE is named "
        "solely as the third-party host module this shield is designed to "
        "plug onto; this is not an STMicroelectronics publication.",
        align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Features
    pdf.add_page()
    pdf.h1("1. Features")
    pdf.bullets(FEATURES)

    # Description
    pdf.add_page()
    pdf.h1("2. Description")
    pdf.para(DESCRIPTION)

    # Host module summary
    pdf.add_page()
    pdf.h1("3. Host Module")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(
        0, 5.4,
        f"This shield does not include a microcontroller of its own. All "
        f"firmware runs on the {HOST_BOARD} it is seated on; the facts below "
        f"are reference information about that host module, not part of "
        f"this document's bill of materials.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    pdf.fact_table(HOST_FACTS)

    # Power architecture
    pdf.add_page()
    pdf.h1("4. Power Architecture")
    pdf.para(POWER_ARCH)

    # Development environment
    pdf.add_page()
    pdf.h1("5. Development Environment")
    pdf.bullets(DEV_ENV)

    # Getting started
    pdf.add_page()
    pdf.h1("6. Assembly and Bring-Up")
    pdf.bullets(GETTING_STARTED)

    # Ordering information
    pdf.add_page()
    pdf.h1("7. Ordering Information")
    pdf.fact_table(ORDERING)

    # Mechanical outline & connector pinout
    pdf.add_page()
    pdf.h1("8. Connector Pinout")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(
        0, 5.4,
        "J1 and J2 are the shield's own screw-terminal and header "
        "connections -- not the Arduino Uno V3 / ST morpho footprint "
        "underneath the board, which is not repeated here.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    pdf.fact_table(CONNECTOR_PINOUT, label_w=42)

    # Test points
    pdf.add_page()
    pdf.h1("9. Test Points and Debug Access")
    pdf.bullets(TEST_POINTS)

    # Safety and compliance
    pdf.add_page()
    pdf.h1("10. Safety and Compliance")
    pdf.bullets(SAFETY)

    # Firmware and examples
    pdf.add_page()
    pdf.h1("11. Firmware and Example Projects")
    pdf.bullets(FIRMWARE_EXAMPLES)
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        0, 5,
        "The bill of materials for this shield begins on the next page. "
        "Board design resources for the host module itself (schematics, "
        "EDA files) are published separately by STMicroelectronics.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def build_bom(pdf: Doc, cat) -> int:
    pdf.bom_mode = True
    pdf.add_page(orientation="L")

    fitted = 0
    for i, (refs, mpn, qty, dnp, alt) in enumerate(LINES, start=1):
        mfr, desc, pkg, life = cat.get(mpn, OUTSIDE.get(mpn, ("", "", "", "")))
        if not dnp:
            fitted += qty

        pdf.set_fill_color(*(ZEBRA if i % 2 == 0 else (255, 255, 255)))
        pdf.set_text_color(*(MUTED if dnp else INK))
        cells = [
            str(i), refs, str(qty), fit(mfr, 30), mpn, fit(desc, 52),
            fit(pkg, 19), life, "Yes", "DNP" if dnp else "", alt,
        ]
        for (_, w), text in zip(COLS, cells):
            pdf.cell(w, 4.6, " " + text, border="LR", fill=True,
                     new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.ln(4.6)

    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + sum(w for _, w in COLS),
             pdf.get_y())
    pdf.ln(4)

    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 5, "Notes", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 7)
    for note in NOTES + [
        f"8. Total line items {len(LINES)}. Placements per shield {fitted}, "
        f"excluding DNP.",
    ]:
        pdf.multi_cell(0, 3.9, note, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # A separate page, not just pdf.ln(): two bordered tables sitting close
    # together with no page boundary between them let pdfplumber's table
    # detector merge them into one, which fed the revision note's own
    # Description text into the BOM table's mpn column in testing -- see
    # parser.py's parse_pdf docstring for the matching fix on the read side.
    pdf.show_columns = False
    pdf.add_page(orientation="L")
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 5, "Revision history", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    hist_cols = [("Rev", 14), ("Date", 26), ("Change ref", 34), ("Description", 178)]
    pdf.set_font("Courier", "B", 6.5)
    pdf.set_fill_color(*HEAD_FILL)
    for name, w in hist_cols:
        pdf.cell(w, 4.6, " " + name, border=1, fill=True,
                 new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.ln(4.6)

    pdf.set_font("Courier", "", 6.5)
    for rev, date, ref, what in [
        ("A", RELEASED, ECO,
         "Initial release: shield BOM for the NUCLEO-G474RE motor-control "
         "carrier, 21 line items."),
    ]:
        for (_, w), text in zip(hist_cols, [rev, date, ref, what]):
            pdf.cell(w, 4.4, " " + fit(text, w), border=1,
                     new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.ln(4.4)

    return fitted


def main() -> int:
    cat = catalogue()

    pdf = Doc(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)

    build_overview(pdf)
    fitted = build_bom(pdf, cat)

    out = Path(__file__).resolve().parents[1] / "samples" / f"{DOCNO}.pdf"
    out.parent.mkdir(exist_ok=True)
    pdf.output(str(out))

    print(f"  wrote {out}")
    print(f"  {pdf.page_no()} pages total")
    print(f"  {len(LINES)} BOM line items, {fitted} placements fitted, "
          f"{sum(1 for l in LINES if l[3])} DNP, "
          f"{sum(1 for l in LINES if l[1] not in cat)} outside the catalogue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
