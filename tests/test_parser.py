"""
BOM parsing.

Every case here is a bug that actually happened, found by putting a realistic
document through the parser rather than a convenient one. They are written as
tests so the next refactor cannot quietly reintroduce them.
"""

from __future__ import annotations

import pytest

from agents.bom_intake.parser import (
    _is_reference, _leading_columns, _looks_like_mpn, find_mpn, parse_bom_file,
)


class TestMpnShape:
    def test_a_reference_designator_is_not_a_part(self):
        """
        Q1-Q6 has letters, digits and a hyphen, so any shape test calls it a
        part number. In a columnar BOM it sits to the LEFT of the real one, so
        without this the designator won and the MPN landed in the description.
        """
        assert _is_reference("Q1-Q6")
        assert _is_reference("C33-C42")
        assert _is_reference("U1")
        assert not _is_reference("STM32F407VGT6")
        assert find_mpn("3 6 Q1-Q6 IRFB4110PBF Infineon") == "IRFB4110PBF"

    def test_a_date_is_not_a_part(self):
        assert find_mpn("Released: 2026-09-01") is None

    def test_a_package_name_is_not_a_part(self):
        assert not _looks_like_mpn("LQFP-100")
        assert not _looks_like_mpn("SOIC-8")

    def test_a_value_with_a_unit_is_not_a_part(self):
        assert not _looks_like_mpn("100nF")
        assert not _looks_like_mpn("25MHz")

    def test_a_real_part_number_is_one(self):
        for mpn in ["STM32F407VGT6", "GRM188R71H104KA93D", "RC0603FR-0710KL"]:
            assert _looks_like_mpn(mpn), mpn


class TestHeaderOrder:
    def test_reads_the_column_order_off_the_header(self):
        """
        PDF extraction discards column positions, so the header line is the only
        surviving statement of the layout. An EMS BOM leads Item, Ref Des, Qty.
        """
        assert _leading_columns(
            "Item Ref Des Qty Manufacturer Manufacturer P/N Description"
        ) == ["item", "refdes", "qty"]

    def test_handles_a_sheet_that_leads_with_quantity(self):
        assert _leading_columns("Qty Reference MPN Description")[:2] == ["qty", "refdes"]

    def test_a_line_with_no_column_names_yields_nothing(self):
        assert _leading_columns("Kestrel Electronics Pvt Ltd") == []


@pytest.mark.parametrize("filename,lines,placements", [
    ("BOM-MC-4000-01-B.pdf", 21, 90),
    ("BOM-MC-4100-01-A.xlsx", 19, 88),
    ("sensor_hub_SH-100.csv", 15, None),
    ("sensor_hub_SH-100.xlsx", 15, None),
    ("sensor_hub_SH-100.txt", 6, None),
    ("sensor_hub_SH-100.pdf", 7, None),
])
def test_fixture_files_parse_to_a_known_shape(samples, filename, lines, placements):
    """The counts every later change is measured against."""
    path = samples / filename
    if not path.exists():
        pytest.skip(f"{filename} not generated")
    rows = parse_bom_file(path)
    assert len(rows) == lines
    if placements is not None:
        assert sum(r["quantity"] for r in rows) == placements


class TestControlledDocument:
    """The released BOM: title block, DNP lines, notes, revision history."""

    @pytest.fixture(scope="class")
    def rows(self, samples):
        path = samples / "BOM-MC-4000-01-B.pdf"
        if not path.exists():
            pytest.skip("fixture not generated")
        return parse_bom_file(path)

    def test_the_title_block_is_not_a_part(self, rows):
        assert not any(r["mpn"].startswith("MC-4000") for r in rows)

    def test_notes_and_revision_history_are_not_parts(self, rows):
        text = " ".join(r["mpn"] for r in rows)
        assert "J-STD-033" not in text
        assert "ECO-2026-0301" not in text

    def test_designator_ranges_are_kept_whole(self, rows):
        refs = {r["reference_designator"] for r in rows}
        assert "Q1-Q6" in refs
        assert "C1-C32" in refs

    def test_quantities_come_from_the_qty_column_not_the_item_number(self, rows):
        by_ref = {r["reference_designator"]: r["quantity"] for r in rows}
        assert by_ref["Q1-Q6"] == 6
        assert by_ref["C1-C32"] == 32

    def test_dnp_lines_are_zero_not_one(self, rows):
        """
        Do-not-populate means on the drawing, not purchased. Clamped to one, as
        it was, the system quietly orders parts nobody asked for.
        """
        by_ref = {r["reference_designator"]: r["quantity"] for r in rows}
        assert by_ref["R27-R28"] == 0
        assert by_ref["C43"] == 0


class TestRefusals:
    def test_an_unreadable_image_raises_a_clear_error(self, tmp_path):
        """
        Not a real refusal any more -- see TestOCR -- but a file that is not
        actually a decodable image (truncated upload, wrong extension) must
        still fail with one sentence a person can act on, not RapidOCR's bare
        "cannot identify image file" or a raw traceback reaching the UI as a
        500.
        """
        image = tmp_path / "bom.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
        with pytest.raises(RuntimeError, match="image"):
            parse_bom_file(image)

    def test_a_blank_scanned_pdf_returns_nothing_rather_than_erroring(self, tmp_path):
        """
        No text layer routes to OCR (TestOCR), and a page with nothing on it
        to read is a legitimately different outcome from a crash: zero lines,
        not an exception -- the UI already treats zero parsed lines as its
        own state, distinct from "something went wrong".
        """
        pytest.importorskip("fpdf")
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        out = tmp_path / "scan.pdf"
        pdf.output(str(out))
        assert parse_bom_file(out) == []


class TestOCR:
    """
    A scan or a photograph, read via agents.bom_intake.ocr (RapidOCR) instead
    of being refused -- see parser.py's module docstring for why, and
    ocr.py's for the accuracy trade this makes.
    """

    @pytest.fixture(scope="class")
    def bom_image(self, tmp_path_factory):
        """
        A synthetic BOM table, rendered as pixels rather than PDF text -- the
        same shape of document a phone photo or a flatbed scan would produce.
        Column gaps wide enough for RapidOCR's text detector to split cells,
        as a real printed table's usually are (see ocr.py's _find_header_row
        docstring for the case where they are not).
        """
        pytest.importorskip("PIL")
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (1000, 260), "white")
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
            font_b = ImageFont.truetype("arialbd.ttf", 24)
        except OSError:
            font = font_b = ImageFont.load_default()

        cols_x = [30, 180, 520, 650]
        rows = [
            ["Ref", "MPN", "Qty", "Description"],
            ["U1", "STM32F407VGT6", "1", "MCU, LQFP-100"],
            ["C1", "GRM188R71H104KA93D", "20", "100nF MLCC 0603"],
        ]
        y = 30
        for i, row in enumerate(rows):
            f = font_b if i == 0 else font
            for x, text in zip(cols_x, row):
                d.text((x, y), text, fill="black", font=f)
            y += 70

        path = tmp_path_factory.mktemp("ocr") / "bom_scan.png"
        img.save(path)
        return path

    def test_mpns_are_read_correctly(self, bom_image):
        pytest.importorskip("rapidocr_onnxruntime")
        rows = parse_bom_file(bom_image)
        mpns = {r["mpn"] for r in rows}
        assert "STM32F407VGT6" in mpns
        assert "GRM188R71H104KA93D" in mpns

    def test_every_row_is_tagged_as_ocr_derived(self, bom_image):
        """
        resolve.py flags an OCR line on every outcome, matched or not, because
        a confident wrong reading looks identical to a confident right one.
        That flag starts here.
        """
        pytest.importorskip("rapidocr_onnxruntime")
        rows = parse_bom_file(bom_image)
        assert rows and all(r.get("source") == "ocr" for r in rows)
