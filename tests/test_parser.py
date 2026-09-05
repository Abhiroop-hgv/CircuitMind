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
    def test_an_image_is_refused_with_a_reason(self, tmp_path):
        image = tmp_path / "bom.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
        with pytest.raises(RuntimeError, match="image"):
            parse_bom_file(image)

    def test_a_pdf_with_no_text_layer_is_refused_rather_than_returning_nothing(
            self, tmp_path):
        """Zero rows and no error reads as "broken", not "this file is a scan"."""
        pytest.importorskip("fpdf")
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        out = tmp_path / "scan.pdf"
        pdf.output(str(out))
        with pytest.raises(RuntimeError, match="no text layer"):
            parse_bom_file(out)
