"""
BOM file parser -- PDF, XLSX, CSV, TSV, plain text, and scanned/photographed
documents (via OCR) into structured line items.

ORIGIN
------
Vendored from CircuitMind by Shruthi-Joshi, `services/backend/app/docai/parser.py`
(https://github.com/Shruthi-Joshi/CircuitMind). Same team, same hackathon.

It was worth taking rather than rewriting: it is genuinely standalone -- only
stdlib plus pypdf and openpyxl, no database, no config, no framework. It takes a
path and returns plain dicts, which is exactly the surface we needed.

CHANGES FROM THE ORIGINAL
-------------------------
One real fix. The original MPN detector was:

    r"[A-Z]{2,}[\\dA-Z]*[-/][\\dA-Za-z.]{3,}"

which REQUIRES a hyphen or slash. That is fine for parts like `RC0603FR-0710KL`,
but it silently misses every hyphen-less part number -- `STM32F407VGT6`,
`GRM188R71H104KA93D`, `IRFB4110PBF`, `TCAN332DR`. Most of our catalogue, in other
words. It never showed up in their testing because CSV and XLSX go through column
detection instead, and only free text, PDF and OCR fall back to the pattern.

Replaced with a token scan plus a shape test (see `find_mpn`), which handles both
styles. Everything else is theirs.

A second change: a scanned PDF (no text layer) or an image file used to be a
hard refusal here -- "reading it needs OCR, which is not wired up". It now
falls to `ocr.py` (RapidOCR, open source, no API key, no network call at
inference time) instead of raising. See that module's docstring for why an
OCR reading is safe to let into the same pipeline as everything else, and
resolve.py's for how it stays visibly flagged once it is in.

KNOWN LIMIT
-----------
Free-text extraction stays heuristic, and always will be: a purely numeric part
like Molex `43045-0400` is genuinely ambiguous with a date or a quantity when it
has no column heading above it. Tabular files are reliable; PDFs are best effort;
OCR is best effort on top of best effort -- see ocr.py for the accuracy trade.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional

try:
    import pdfplumber  # type: ignore
except ImportError:  # pragma: no cover
    pdfplumber = None  # type: ignore

try:
    from pypdf import PdfReader  # type: ignore
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore

try:
    from openpyxl import load_workbook  # type: ignore
except ImportError:  # pragma: no cover
    load_workbook = None  # type: ignore


@dataclass
class BOMRow:
    """One line item, normalised out of whatever format it arrived in."""
    line_number: int
    reference_designator: str
    mpn: str
    quantity: int
    description: str


# ── MPN detection ─────────────────────────────────────────────────────────────

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./+-]{3,}")

_REF_DES_PATTERN = re.compile(r"\b([CRULDJTQSPVY]\d{1,4})\b", re.IGNORECASE)
_QTY_PATTERN = re.compile(r"\b(\d{1,6})\b")

# A whole reference designator, including a range: U1, Q1-Q6, C33-C42, R17-R22.
# These read exactly like part numbers to a shape test -- letters, digits and a
# hyphen -- and in a columnar BOM they sit to the LEFT of the real part number,
# so without this the designator wins and the actual MPN is left in the
# description. Cost a wrong part number on six of nineteen lines the first time
# the PDF path met a realistic document.
_REF_DES_WHOLE = re.compile(
    r"^[A-Z]{1,3}\d{1,4}(?:\s*-\s*[A-Z]{0,3}\d{1,4})?$", re.IGNORECASE)

# Title blocks carry dates. A date is not a part.
_DATE_LIKE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$|^\d{1,2}/\d{1,2}/\d{2,4}$")

# Package names read exactly like part numbers to any shape test -- LQFP-100 has
# letters, digits and a hyphen. Matched on the leading alphabetic run so
# LQFP-100, SOIC-8 and TO-220AB are all caught.
_PACKAGE_PREFIXES = {
    "lqfp", "qfp", "soic", "so", "tssop", "ssop", "msop", "qfn", "dfn", "sot",
    "to", "sod", "smd", "smc", "sma", "dip", "pdip", "bga", "csp", "wson",
}

# A value with a unit is a spec, not a part: 100nF, 10k, 4u7, 25MHz.
_VALUE_WITH_UNIT = re.compile(
    r"^\d+[.,]?\d*\s*(nf|uf|pf|mf|f|mh|uh|nh|k|m|r|ohm|ohms|v|mv|kv|ma|a|w|mw"
    r"|hz|khz|mhz|ghz|ppm|pct|%|mm|cm|in|deg|c)$",
    re.IGNORECASE,
)


def _looks_like_mpn(token: str) -> bool:
    """
    Shape test for a manufacturer part number.

    Real MPNs mix letters and digits and run to at least five characters. That
    catches both `STM32F407VGT6` and `RC0603FR-0710KL`, and rejects bare words,
    bare numbers, package names and spec values.
    """
    if len(token) < 5:
        return False

    letters = sum(c.isalpha() for c in token)
    digits = sum(c.isdigit() for c in token)
    if digits < 2:
        return False

    if _VALUE_WITH_UNIT.match(token):
        return False

    leading_alpha = re.match(r"^[A-Za-z]+", token)
    if leading_alpha and leading_alpha.group().lower() in _PACKAGE_PREFIXES:
        return False

    # Either genuinely alphanumeric, or a hyphenated numeric part like 43045-0400
    return letters >= 2 or ("-" in token and digits >= 6)


# A controlled BOM ends its item table with a notes or revision block. Those
# lines carry part-number-shaped text -- J-STD-033, ECO-2026-0301 -- and read as
# components to any shape test, so the table has to be bounded rather than
# filtered line by line.
_TABLE_END = re.compile(r"^(notes?|revision history|approvals?|change history)\b",
                        re.IGNORECASE)

_DNP = re.compile(r"\bDN[PI]\b", re.IGNORECASE)


def _leading_columns(header: str) -> list:
    """
    Which of item / reference / quantity lead the row, and in what order.

    PDF extraction throws away column positions -- every run of spaces collapses
    to one -- so the header line is the only surviving statement of the layout.
    An EMS BOM leads "Item Ref Des Qty"; a hand-written one often leads
    "Reference MPN Qty". Reading the order off the header is the difference
    between knowing which number is the quantity and guessing.
    """
    found = {}
    for i, token in enumerate(header.lower().split()):
        t = token.strip(".:,")
        if t == "item" and "item" not in found:
            found["item"] = i
        elif t.startswith(("ref", "desig")) and "refdes" not in found:
            found["refdes"] = i
        elif t.startswith(("qty", "quantit")) and "qty" not in found:
            found["qty"] = i
    return [k for k, _ in sorted(found.items(), key=lambda kv: kv[1])]


def _is_reference(token: str) -> bool:
    """True for U1 or Q1-Q6 -- a position on the board, not a part."""
    return bool(_REF_DES_WHOLE.match(token or ""))


def find_mpn(text: str) -> Optional[str]:
    """First token in `text` that looks like a part number, or None."""
    for match in _TOKEN.finditer(text or ""):
        token = match.group().strip(".,;:|")
        if _is_reference(token) or _DATE_LIKE.match(token):
            continue
        if _looks_like_mpn(token):
            return token
    return None


def _try_int(val: Any) -> int:
    try:
        return max(1, int(float(val)))
    except (TypeError, ValueError):
        return 1


def _clean(val: Any) -> str:
    return "" if val is None else str(val).strip()


# ── Format-specific extractors ────────────────────────────────────────────────

# A page of a born-digital PDF carries hundreds of characters. A scanned page
# carries none, because the table is pixels. Twenty per page sits comfortably
# below anything real and above the stray artefact a scanner leaves behind.
_TEXT_PER_PAGE_FLOOR = 20


# Column headings, in the order they must be claimed. "Manufacturer P/N" and
# "Manufacturer" both contain the word manufacturer, and "Ref. description"
# contains both reference and description, so the more specific name has to get
# first refusal or the wrong column wins.
_COLUMN_ALIASES = [
    ("mpn", ("manufacturer p/n", "manufacturer part", "mfr p/n", "mfg p/n",
             "mpn", "part number", "part no", "part #")),
    ("qty", ("qty", "quantity")),
    ("ref", ("ref", "reference", "designator", "refdes")),
    ("dnp", ("dnp", "dni", "populate", "fitted")),
    ("desc", ("description", "value", "comment")),
    ("mfr", ("manufacturer", "mfr", "mfg", "supplier")),
]


def _map_columns(header: List) -> Dict[str, int]:
    """Header cells to field names. Unmatched columns are simply ignored."""
    mapping: Dict[str, int] = {}
    taken = set()
    for field, aliases in _COLUMN_ALIASES:
        for i, cell in enumerate(header):
            if i in taken:
                continue
            low = str(cell or "").strip().lower()
            if low and any(a in low for a in aliases):
                mapping[field] = i
                taken.add(i)
                break
    return mapping


def _cell(row: List, index: Optional[int]) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def parse_pdf_tables(filepath) -> List[dict]:
    """
    Read the BOM out of the PDF's actual table cells.

    Plain text extraction throws away column boundaries: a published manual came
    back with item 2 quantity 58 fused into the token "25 8", and a fifty-eight
    designator cell spread over six lines with no way to tell which row it
    belonged to. The ruling lines that make it a table are still in the file, so
    read those instead of trying to reconstruct them from spacing.

    Returns [] when the document has no table this recognises, which leaves the
    text path to try.
    """
    if pdfplumber is None:
        return []

    results: List[dict] = []
    line_num = 0

    with pdfplumber.open(str(filepath)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                cols = _map_columns(table[0])
                if "mpn" not in cols:
                    continue

                for row in table[1:]:
                    # A wrapped cell breaks the part number across lines. Those
                    # halves are one number: "GRM155R71C104KA8" + "8D".
                    mpn = "".join(_cell(row, cols.get("mpn")).split("\n")).strip()
                    if not mpn or not _looks_like_mpn(mpn) or _is_reference(mpn):
                        continue

                    ref = " ".join(_cell(row, cols.get("ref")).split())
                    qty = _try_int(_cell(row, cols.get("qty")) or 1)
                    if _DNP.search(_cell(row, cols.get("dnp")) or ""):
                        qty = 0

                    desc = " ".join(
                        (_cell(row, cols.get("desc")) + " " +
                         _cell(row, cols.get("mfr"))).split())

                    line_num += 1
                    results.append(asdict(BOMRow(line_num, ref, mpn, qty, desc)))

    return results


def parse_pdf(filepath) -> List[dict]:
    if PdfReader is None:
        raise RuntimeError("pypdf not installed -- pip install pypdf")
    reader = PdfReader(str(filepath))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # A page of a born-digital PDF carries hundreds of characters of real
    # text; a scanned or photographed page carries none, because the table is
    # pixels, not text objects. That used to be a dead end -- see ocr.py,
    # which reads pixels instead and is what a page this thin now falls to.
    pages = max(1, len(reader.pages))
    if len(text.strip()) < _TEXT_PER_PAGE_FLOOR * pages:
        from .ocr import ocr_pdf_file  # lazy: only a scan pulls in RapidOCR

        return ocr_pdf_file(filepath)

    # Try the cells first, and prefer them whenever they found anything.
    # parse_pdf_tables only emits a row from a table pdfplumber actually
    # detected, with a header it recognised as naming an "mpn" column -- a
    # structural guarantee the free-text path has none of. That used to be
    # "whichever path found more rows", which reads as reasonable until a
    # real document is a datasheet with the BOM as one table among several
    # pages of prose: page text like "STM32G474RET6" or "NUCLEO-G474RE" is
    # shaped exactly like a part number to find_mpn, and a document with
    # enough of that prose outweighs the table's genuinely correct rows on
    # count alone, discarding the accurate extraction for the noisy one. The
    # text path stays the fallback for what parse_pdf_tables cannot see at
    # all: a typeset manual with no ruling lines, or an exported sheet whose
    # columns are drawn with spacing rather than a real table structure.
    from_tables = parse_pdf_tables(filepath)
    if from_tables:
        return from_tables
    return _parse_text(text)


def parse_xlsx(filepath) -> List[dict]:
    if load_workbook is None:
        raise RuntimeError("openpyxl not installed -- pip install openpyxl")
    wb = load_workbook(str(filepath), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        return []
    rows = [[_clean(c) for c in row] for row in ws.iter_rows(values_only=True)]
    wb.close()
    return _parse_tabular(rows)


def parse_csv(filepath) -> List[dict]:
    text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    return _parse_tabular([[_clean(c) for c in row] for row in reader])


def parse_text(text: str) -> List[dict]:
    return _parse_text(text)


# ── Core helpers ──────────────────────────────────────────────────────────────

_COLUMN_KEYWORDS = {
    "mpn": ["mpn", "part", "mfr part", "manufacturer part", "mfg part",
            "p/n", "part number", "part no"],
    "ref": ["ref", "designator", "reference", "refdes"],
    "qty": ["qty", "quantity", "count", "amount", "per board"],
    "desc": ["desc", "description", "name", "component", "value"],
    "dnp": ["dnp", "dni", "populate", "fitted"],
}


def _guess_columns(header: List[str]) -> dict:
    mapping = {k: None for k in _COLUMN_KEYWORDS}
    for idx, cell in enumerate(header):
        low = cell.lower()
        for key, words in _COLUMN_KEYWORDS.items():
            if mapping[key] is None and any(w in low for w in words):
                mapping[key] = idx
    return mapping


def _header_row(rows: List[List[str]], limit: int = 25) -> int:
    """
    The row that names the columns, which is rarely the first one.

    A released BOM opens with a title block -- company, assembly number,
    approvals -- and the column header sits several rows below it. Taking the
    first non-empty row instead, as this did, mapped no columns at all: every
    quantity silently fell back to 1, "Q1-Q6" was truncated to "Q1" by the
    designator regex, and the title block itself was read as a part.

    Scored rather than matched, so the row naming the most columns wins.
    """
    best, best_score = 0, 0
    for i, row in enumerate(rows[:limit]):
        if not any(row):
            continue
        score = sum(
            1 for key, words in _COLUMN_KEYWORDS.items()
            if any(any(w in (cell or "").lower() for w in words) for cell in row)
        )
        if score > best_score:
            best, best_score = i, score
    # Two named columns is enough to be a header; below that, assume the sheet
    # has none and start from the first row with anything in it.
    if best_score >= 2:
        return best
    return next((i for i, r in enumerate(rows) if any(r)), 0)


def _parse_tabular(rows: List[List[str]]) -> List[dict]:
    """CSV and XLSX: header detection, then column extraction. The reliable path."""
    if not rows:
        return []

    header_idx = _header_row(rows)
    col_map = _guess_columns(rows[header_idx])
    results: List[dict] = []
    line_num = 0

    for row in rows[header_idx + 1:]:
        if not any(row):
            continue

        mpn = ref = desc = ""
        qty = 1

        if col_map["mpn"] is not None and col_map["mpn"] < len(row):
            mpn = row[col_map["mpn"]]
        if col_map["ref"] is not None and col_map["ref"] < len(row):
            ref = row[col_map["ref"]]
        if col_map["qty"] is not None and col_map["qty"] < len(row):
            qty = _try_int(row[col_map["qty"]])

        # "Do not populate": on the drawing, not to be bought. Zero rather than
        # dropped, so the line stays visible and nothing downstream orders it.
        if col_map.get("dnp") is not None and col_map["dnp"] < len(row):
            if _DNP.search(row[col_map["dnp"]] or ""):
                qty = 0
        if col_map["desc"] is not None and col_map["desc"] < len(row):
            desc = row[col_map["desc"]]

        if not mpn:
            for cell in row:
                found = find_mpn(cell)
                if found:
                    mpn = found
                    break
        if not mpn:
            continue

        if not ref:
            for cell in row:
                m = _REF_DES_PATTERN.search(cell)
                if m:
                    ref = m.group()
                    break

        if not desc:
            desc = " ".join(c for c in row if c and c not in (mpn, ref))

        line_num += 1
        results.append(asdict(BOMRow(line_num, ref, mpn.strip(), qty, desc.strip())))

    return results


def _parse_text(text: str) -> List[dict]:
    """Unstructured text from a PDF or a paste. Best effort by nature."""
    results: List[dict] = []
    line_num = 0

    # When the document declares its columns, trust that over any heuristic, and
    # read only the rows that belong to the item table. Everything above the
    # header is a title block and everything below the notes heading is prose.
    lines = text.splitlines()
    header_at, order = -1, []
    for i, line in enumerate(lines[:40]):
        low = line.lower()
        if sum(1 for w in _HEADER_WORDS if w in low) >= 2:
            found = _leading_columns(line)
            if found:
                header_at, order = i, found
                break
    if header_at >= 0:
        lines = lines[header_at + 1:]
    skip_words = ("bill of materials", "reference", "part number", "---", "===",
                  "total:", "notes:", "rev ", "document ", "prepared by",
                  "released ", "confidential", "page ", "total line items")

    for raw in lines:
        line = raw.strip()
        if _TABLE_END.match(line):
            break
        if not line or any(s in line.lower() for s in skip_words):
            continue

        # Pipe-delimited tables survive PDF extraction fairly often.
        if "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 3:
                candidate = find_mpn(parts[1]) if len(parts) > 1 else None
                if candidate:
                    line_num += 1
                    results.append(asdict(BOMRow(
                        line_num, parts[0], candidate,
                        _try_int(parts[2]) if len(parts) > 2 else 1,
                        parts[3] if len(parts) > 3 else "")))
                    continue

        mpn = find_mpn(line)
        if not mpn:
            continue

        # Consume the leading columns in the order the header declared. Only a
        # token of the right shape is accepted, so a row that does not match the
        # declared layout falls through to the heuristics below rather than
        # taking a manufacturer name for a quantity.
        tokens = line.split()
        ref, qty_declared, cursor = "", None, 0
        for field in order:
            if cursor >= len(tokens):
                break
            token = tokens[cursor].strip(".,;:|")
            if field == "item" and token.isdigit():
                cursor += 1
            elif field == "refdes" and _is_reference(token):
                ref = token
                cursor += 1
            elif field == "qty" and token.isdigit():
                qty_declared = int(token)
                cursor += 1
            else:
                break

        # Keep the designator whole, so a range stays "Q1-Q6" rather than "Q1".
        if not ref:
            for token in tokens:
                cleaned = token.strip(".,;:|")
                if _is_reference(cleaned):
                    ref = cleaned
                    break
        if not ref:
            ref_match = _REF_DES_PATTERN.search(line)
            ref = ref_match.group() if ref_match else ""

        # An exported BOM usually leads with an item number, so the FIRST
        # integer on a line is the row index and the second is the quantity.
        # The meaningful one is the integer closest to the part, so take the
        # last integer before it, and only fall back to the first one after.
        if qty_declared is not None:
            qty = max(1, qty_declared)
        else:
            anchor_at = line.find(ref) if ref else line.find(mpn)
            if anchor_at < 0:
                anchor_at = len(line)
            before = _QTY_PATTERN.findall(line[:anchor_at])
            if before:
                qty = _try_int(before[-1])
            else:
                after = _QTY_PATTERN.search(line[anchor_at:].replace(mpn, "", 1))
                qty = _try_int(after.group(1)) if after else 1

        # "Do not populate": the part is on the drawing and must not be bought.
        # Kept in the output rather than dropped -- a line that silently vanishes
        # is harder to trust than one that shows a quantity of zero -- but at
        # zero, so nothing downstream orders it.
        if _DNP.search(line):
            qty = 0

        remaining = line.replace(mpn, "").replace(ref, "")

        line_num += 1
        results.append(asdict(BOMRow(
            line_num, ref, mpn.strip(), qty, remaining.strip(" \t,;|"))))

    return results


# ── Dispatcher ────────────────────────────────────────────────────────────────

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif"}

_HEADER_WORDS = ("mpn", "part", "qty", "quantity", "reference", "designator",
                 "refdes", "description")


def _has_column_header(text: str) -> bool:
    """True when an early line names at least two BOM columns."""
    for line in text.splitlines()[:8]:
        low = line.lower()
        if sum(1 for w in _HEADER_WORDS if w in low) >= 2:
            return True
    return False


def parse_bom_file(filepath) -> List[dict]:
    """Detect the format and return structured BOM rows."""
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    if ext in IMAGE_EXTS:
        from .ocr import ocr_image_file  # lazy: only an image pulls in RapidOCR

        return ocr_image_file(filepath)
    if ext == ".pdf":
        return parse_pdf(filepath)
    if ext in (".xlsx", ".xls"):
        return parse_xlsx(filepath)
    if ext in (".csv", ".tsv"):
        return parse_csv(filepath)
    if ext == ".txt":
        # A .txt file can be either a delimited table or free prose, and the
        # csv sniffer cannot tell: it treats "|" as a delimiter, so a
        # pipe-drawn text table parses as a table whose header row is the
        # document title. Every column then goes unrecognised and quantities
        # silently default to 1. Decide by looking for real column headings.
        text = filepath.read_text(encoding="utf-8", errors="replace")
        return parse_csv(filepath) if _has_column_header(text) else _parse_text(text)

    try:
        return parse_csv(filepath)
    except Exception:
        return _parse_text(filepath.read_text(encoding="utf-8", errors="replace"))
