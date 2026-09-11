"""
OCR for a BOM that arrives as a scan or a photograph rather than an exported
document -- the case parser.py used to refuse outright:

    "This is an image. Reading one means a model transcribing the figures,
     with nothing to check them against, so it is deliberately not supported."

That objection turned out to be wrong on its own terms: there IS something to
check an OCR reading against -- the same catalogue match every other intake
path already goes through (resolve.py), which is exact-or-normalised only and
never fuzzy. A misread character either fails to match and falls to UNKNOWN,
ranked for a human like any other unresolved line, or -- rarely -- collides
with a different real part, a risk a typo in a hand-typed BOM already carries
today. OCR does not introduce a new failure mode; it makes an existing one
somewhat more likely, which is a reason to flag its output, not refuse it.

RAPIDOCR, NOT A HOSTED VISION MODEL
------------------------------------
`pip install rapidocr-onnxruntime` ships its own ONNX text-detection and
text-recognition weights inside the wheel -- no API key, no network call at
inference time, no per-page cost. That matters more here than a marginal
accuracy gain would: this project runs offline as a first-class mode
(scripts/demo.py --offline, a Render deploy with no key set), and an intake
path that silently stops working whenever a key is absent is worse than one
that always works, a little less accurately. pypdfium2 rasterises a scanned
PDF's pages to images first, the same way a phone camera or a flatbed scanner
already turned the original document into pixels -- OCR reads pixels, and a
scanned PDF carries none of the extractable text or ruling lines the
non-OCR PDF path (parser.parse_pdf) depends on.

THE ACCURACY TRADE, STATED PLAINLY
------------------------------------
OCR misreads characters, and it does so with unhelpfully high confidence: a
"6" read as "9" scored 0.997 in testing -- not appreciably lower than a
correct reading alongside it. So this module does not use its own confidence
score to decide what needs a second look. Instead every row it produces is
tagged `source: "ocr"`, and resolve.py surfaces that on every single line it
resolves, matched or not -- see resolve.py's module docstring. A clean match
is still shown as OCR-derived, because a confident wrong digit looks exactly
like a confident right one until a person checks it against the document.

WHAT THIS DOES NOT DO
------------------------
It does not have a language model -- or anything else -- reason about the
image or guess at what a component "probably" is. It detects text regions and
reads the characters printed in them. That is the same "model reads, code
decides" split as everywhere else in this project (CLAUDE.md invariant 1):
OCR proposes a token stream, and the existing shape tests in parser.py
(find_mpn, _looks_like_mpn) and the existing catalogue match in resolve.py
decide what, if anything, it means.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from typing import List

from .parser import (
    BOMRow,
    _cell,
    _COLUMN_KEYWORDS,
    _DNP,
    _map_columns,
    _parse_text,
    _QTY_PATTERN,
    _REF_DES_PATTERN,
    _try_int,
    find_mpn,
)

# A page of a born-digital PDF renders crisply at screen resolution; a photo
# or a flatbed scan needs real resolution for small print (a 0603 MLCC's
# printed value, a QFN's part marking) to survive as legible pixels rather
# than a grey smear. 300 DPI is the conventional OCR floor for exactly that
# reason -- pypdfium2's `scale` is relative to a PDF's native 72 DPI unit.
_DEFAULT_DPI = 300

_engine = None  # built once per process -- loading the ONNX models takes a
                # couple of seconds, and a multi-page PDF has no reason to
                # pay that more than once.


def _get_engine():
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR  # heavy; kept lazy
        except ImportError as exc:
            raise RuntimeError(
                "OCR needs rapidocr-onnxruntime, which is not installed.\n"
                "    pip install rapidocr-onnxruntime pypdfium2"
            ) from exc
        _engine = RapidOCR()
    return _engine


@dataclass
class _Box:
    """One detected text region: its reading and where it sits on the page."""
    text: str
    score: float
    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def _to_boxes(raw_result) -> List[_Box]:
    boxes = []
    for quad, text, score in raw_result or []:
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        text = (text or "").strip()
        if text:
            boxes.append(_Box(text=text, score=float(score),
                              x0=min(xs), x1=max(xs), y0=min(ys), y1=max(ys)))
    return boxes


def _cluster_rows(boxes: List[_Box]) -> List[List[_Box]]:
    """
    Group text boxes into table rows by vertical position.

    There is no ruling line to read a scanned table's rows off, the way
    parse_pdf_tables reads a born-digital PDF's. A row is instead a run of
    boxes whose vertical centres fall within a bit over half a box-height of
    the row's own centre -- generous enough for the few pixels of baseline
    jitter a real photograph produces, tight enough that two stacked rows of
    normal-sized print never merge into one.
    """
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda b: b.cy)
    tol = statistics.median(b.height for b in ordered) * 0.6

    rows: List[List[_Box]] = [[ordered[0]]]
    row_cy = ordered[0].cy
    for b in ordered[1:]:
        if abs(b.cy - row_cy) <= tol:
            rows[-1].append(b)
            row_cy = statistics.mean(x.cy for x in rows[-1])
        else:
            rows.append([b])
            row_cy = b.cy

    for row in rows:
        row.sort(key=lambda b: b.x0)
    return rows


def _find_header_row(rows: List[List[_Box]], limit: int = 10) -> int:
    """
    Which clustered row actually names the columns.

    A released BOM's scan carries a title block above the table -- company
    name, board name, "Bill of Materials" -- exactly like parser._header_row
    already has to work around for a tabular file. Above the real header that
    title line is also usually ONE wide text box (no internal column gap for
    the detector to split on), so assuming row 0 is the header collapses
    every later column onto that single anchor. Scored the same way
    parser._header_row scores a text line: the row naming the most distinct
    BOM columns wins, not simply the first one.
    """
    best, best_score = 0, 0
    for i, row in enumerate(rows[:limit]):
        texts = [b.text for b in row]
        score = sum(
            1 for words in _COLUMN_KEYWORDS.values()
            if any(any(w in t.lower() for w in words) for t in texts)
        )
        if score > best_score:
            best, best_score = i, score
    return best if best_score >= 2 else 0


def _rows_to_table(rows: List[List[_Box]]) -> List[List[str]]:
    """
    Snap every row's boxes onto the header row's column positions.

    The header row IS the column layout here -- there are no cell boundaries
    to read the way a born-digital PDF's table does. Every later box joins
    whichever header column its centre sits closest to; two boxes snapping to
    the same column (a cell OCR happened to split into two detections) join
    with a space, the same as a wrapped cell does in parse_pdf_tables.
    """
    if not rows:
        return []
    header_at = _find_header_row(rows)
    header, data_rows = rows[header_at], rows[header_at + 1:]

    anchors = [b.cx for b in header]
    table = [[b.text for b in header]]

    for row in data_rows:
        cells = [""] * len(anchors)
        for b in row:
            nearest = min(range(len(anchors)), key=lambda i: abs(anchors[i] - b.cx))
            cells[nearest] = (cells[nearest] + " " + b.text).strip()
        table.append(cells)
    return table


def _table_rows_from_boxes(boxes: List[_Box]) -> List[dict]:
    """
    The structured path: works when the image has a recognisable header row.

    A cell here is a box snapped to the nearest header anchor, not a cell read
    off a real ruling line -- two adjacent header labels with too little gap
    between them for the text detector to split (seen in testing: a released
    BOM's "Reference" and "MPN" column headings, printed close enough to come
    back as one box) collapse their data columns together the same way. Each
    field is therefore pulled out of its cell with the same shape-aware
    extraction the free-text path uses (find_mpn, the reference and quantity
    patterns) instead of trusting the cell's raw text verbatim, so a fused
    "U1 STM32F407VGT6" cell still yields the right MPN rather than failing or,
    worse, being accepted whole as one.
    """
    table = _rows_to_table(_cluster_rows(boxes))
    if len(table) < 2:
        return []

    cols = _map_columns(table[0])
    if "mpn" not in cols:
        return []

    results: List[dict] = []
    line_num = 0
    for row in table[1:]:
        mpn_cell = _cell(row, cols.get("mpn"))
        mpn = find_mpn(mpn_cell)
        if not mpn:
            continue

        ref = _cell(row, cols.get("ref"))
        if not ref:
            # The reference designator may have landed in the same fused
            # cell as the part number (see the docstring above).
            ref_match = _REF_DES_PATTERN.search(mpn_cell)
            ref = ref_match.group() if ref_match else ""

        qty_cell = _cell(row, cols.get("qty"))
        qty_match = _QTY_PATTERN.search(qty_cell)
        qty = _try_int(qty_match.group()) if qty_match else 1
        if _DNP.search(_cell(row, cols.get("dnp")) or ""):
            qty = 0

        desc = " ".join(
            (_cell(row, cols.get("desc")) + " " + _cell(row, cols.get("mfr"))).split())

        line_num += 1
        row_dict = asdict(BOMRow(line_num, ref, mpn, qty, desc))
        row_dict["source"] = "ocr"
        results.append(row_dict)
    return results


def _text_rows_from_boxes(boxes: List[_Box]) -> List[dict]:
    """
    The fallback path: no header recognised, so hand the same row text a
    free-text PDF extraction would produce to the existing heuristic parser
    (parser._parse_text) rather than duplicating its quantity/reference/DNP
    logic here.
    """
    text = "\n".join(" ".join(b.text for b in row) for row in _cluster_rows(boxes))
    out = []
    for row in _parse_text(text):
        row["source"] = "ocr"
        out.append(row)
    return out


def _rows_from_image(image) -> List[dict]:
    """image: a file path, or anything RapidOCR/opencv accepts (a PIL Image
    works via numpy conversion; pass a path where possible -- it is what
    RapidOCR is tested against upstream)."""
    engine = _get_engine()
    try:
        raw_result, _elapsed = engine(image)
    except Exception as exc:
        # RapidOCR's own error for a file that is not actually a decodable
        # image is a bare "cannot identify image file <path>" with no
        # indication of why -- truncated upload, wrong extension on a file
        # that is not an image at all, corrupted transfer. One sentence a
        # person can act on beats that traceback surfacing as a raw 500.
        raise RuntimeError(
            f"Could not read this as an image ({type(exc).__name__}: {exc}). "
            f"Check that the file opens as a picture and try again, or supply "
            f"the BOM as CSV, XLSX, or a PDF exported from the CAD tool."
        ) from exc
    boxes = _to_boxes(raw_result)

    from_table = _table_rows_from_boxes(boxes)
    from_text = _text_rows_from_boxes(boxes)
    # Same rule parse_pdf already uses for its own two extraction paths:
    # keep whichever found more lines, rather than committing to the
    # structured path unconditionally.
    return from_table if len(from_table) >= len(from_text) else from_text


def ocr_image_file(filepath) -> List[dict]:
    """One photograph or scan of a BOM table, as an image file."""
    return _rows_from_image(str(filepath))


def ocr_pdf_file(filepath, dpi: int = _DEFAULT_DPI) -> List[dict]:
    """
    A scanned or photographed PDF: pages rasterised to images first, since
    OCR reads pixels and a PDF like this carries no extractable text layer
    for parser.parse_pdf to read (that is exactly the condition that routes a
    file here -- see parser.parse_pdf's text-per-page check).
    """
    import pypdfium2 as pdfium  # lazy: only a scanned PDF needs a rasteriser

    import numpy as np  # already a hard dependency (requirements.txt, statsmodels)

    pdf = pdfium.PdfDocument(str(filepath))
    results: List[dict] = []
    try:
        for page in pdf:
            bitmap = page.render(scale=dpi / 72)
            # RapidOCR takes a path, bytes or an ndarray -- not a PIL Image.
            rgb = np.asarray(bitmap.to_pil().convert("RGB"))
            for row in _rows_from_image(rgb):
                row = dict(row)
                row["line_number"] = len(results) + 1
                results.append(row)
    finally:
        pdf.close()
    return results
