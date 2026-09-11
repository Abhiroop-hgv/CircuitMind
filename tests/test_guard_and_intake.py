"""
The hallucination guard, quantity handling, and the purchase-order gate.

Three separate things, grouped because each one enforces a promise the project
makes out loud: the model does not invent numbers, a do-not-populate line is not
purchased, and nothing produces a purchase order without a person.
"""

from __future__ import annotations

import pytest

from agents.assistant.guard import REFUSAL, check
from agents.bom_intake.intake import apply_overrides
from agents.bom_intake.resolve import _quantity, normalise

STOCK_CALL = [{
    "tool": "stock_position",
    "arguments": {"part": "STM32F407VGT6"},
    "result": {"on_hand": 7700, "reserved_for_other_jobs": 1200,
               "safety_stock": 500, "usable_now": 6000},
}]


class TestGuardBlocks:
    def test_figures_with_no_tool_call_are_replaced(self):
        answer, unverified = check("You have about 5,000 units left.", [])
        assert answer == REFUSAL
        assert unverified == []

    def test_prose_with_no_figures_is_left_alone(self):
        text = "A gate driver switches power transistors."
        assert check(text, [])[0] == text

    def test_a_traced_figure_passes_untouched(self):
        answer, unverified = check("Usable now: 6,000 units (7700 - 1200 - 500).",
                                   STOCK_CALL)
        assert "6,000" in answer
        assert unverified == []

    def test_a_figure_in_no_result_is_flagged_not_suppressed(self):
        """
        Usually the model doing arithmetic. Hiding a real answer over that would
        be worse than showing a caution beside it.
        """
        answer, unverified = check("6,000 units, about 42% of capacity.", STOCK_CALL)
        assert "42" in unverified
        assert "6,000" in answer

    def test_digits_inside_a_part_code_are_not_claims(self):
        assert check("The STM32F407VGT6 has 6000 usable.", STOCK_CALL)[1] == []

    def test_a_figure_the_user_supplied_is_not_an_invention(self):
        _, unverified = check("2026-09 is covered.", STOCK_CALL,
                              question="what about 2026-09?")
        assert unverified == []

    def test_rounding_is_tolerated(self):
        calls = [{"tool": "supplier_reliability", "arguments": {},
                  "result": {"on_time_score": 0.529}}]
        assert check("Their on-time score is 0.53.", calls)[1] == []


class TestQuantity:
    def test_missing_quantity_means_one(self):
        assert _quantity(None) == 1
        assert _quantity("") == 1
        assert _quantity("not a number") == 1

    def test_explicit_zero_is_preserved(self):
        """Zero is how a line is marked do-not-populate. Clamping it buys parts."""
        assert _quantity(0) == 0
        assert _quantity("0") == 0

    def test_negatives_do_not_become_orders(self):
        assert _quantity(-5) == 1


class TestOverrides:
    def test_quantity_edits_apply(self):
        rows = [{"line_number": 1, "mpn": "STM32F407VGT6", "quantity": 1}]
        assert apply_overrides(rows, {"1": {"quantity": 4}})[0]["quantity"] == 4

    def test_an_unknown_part_can_be_resolved_by_a_person(self):
        rows = [{"line_number": 2, "mpn": "MCP2515-I/SO", "quantity": 1}]
        assert apply_overrides(rows, {"2": {"mpn": "MCP2551-I/SN"}})[0]["mpn"] \
            == "MCP2551-I/SN"

    def test_a_line_number_that_does_not_exist_is_ignored(self):
        rows = [{"line_number": 1, "mpn": "X1234", "quantity": 1}]
        assert apply_overrides([dict(r) for r in rows], {"99": {"quantity": 7}}) == rows

    def test_an_unreadable_quantity_leaves_the_line_alone(self):
        rows = [{"line_number": 1, "mpn": "X1234", "quantity": 2}]
        assert apply_overrides(rows, {"1": {"quantity": "bad"}})[0]["quantity"] == 2

    def test_no_overrides_is_a_no_op(self):
        rows = [{"line_number": 1, "mpn": "X1234", "quantity": 2}]
        assert apply_overrides([dict(r) for r in rows], None) == rows


class TestNormalise:
    def test_case_and_punctuation_are_ignored_when_matching(self):
        assert normalise("stm32f407vgt6") == normalise("STM32F407VGT6")


class TestOCRProvenance:
    """
    An OCR-derived line is flagged in resolve.py's note on every outcome, not
    only when it fails to match -- see resolve.py's module docstring for why
    a clean match is not evidence the reading was correct.
    """

    def test_a_matched_ocr_line_is_still_flagged(self, conn):
        from agents.bom_intake.resolve import resolve_lines
        with conn.cursor() as cur:
            cur.execute("SELECT mpn FROM erp.components LIMIT 1")
            mpn = cur.fetchone()[0]

        clean = resolve_lines(conn, [{"line_number": 1, "mpn": mpn, "quantity": 1}])
        assert clean[0].note == ""

        ocr = resolve_lines(
            conn, [{"line_number": 1, "mpn": mpn, "quantity": 1, "source": "ocr"}])
        assert ocr[0].resolution == clean[0].resolution == "EXACT"
        assert "OCR" in ocr[0].note

    def test_an_unmatched_ocr_line_keeps_both_reasons(self, conn):
        from agents.bom_intake.resolve import resolve_lines
        rows = resolve_lines(conn, [
            {"line_number": 1, "mpn": "NOT-A-REAL-PART-9999",
             "quantity": 1, "source": "ocr"},
        ])
        assert rows[0].resolution == "UNKNOWN"
        assert "not in the component catalogue" in rows[0].note
        assert "OCR" in rows[0].note


class TestPurchaseOrderGate:
    """A purchase order that needs no person is not a gate, it is a formality."""

    def test_an_unapproved_recommendation_produces_nothing(self, conn):
        from agents.procurement.po import NotApproved, build
        with conn.cursor() as cur:
            cur.execute("""SELECT id FROM platform.purchase_recommendations
                            WHERE status <> 'APPROVED' LIMIT 1""")
            row = cur.fetchone()
        if row is None:
            pytest.skip("nothing pending to test the refusal with")
        with pytest.raises(NotApproved, match="approved"):
            build(conn, row[0])

    def test_a_missing_recommendation_is_refused(self, conn):
        from agents.procurement.po import NotApproved, build
        with pytest.raises(NotApproved):
            build(conn, 999_999)
