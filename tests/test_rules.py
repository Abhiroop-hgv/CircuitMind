"""
The compatibility gate.

These are the checks that decide whether a part can go on a board, so they are
the ones a refactor must not quietly change. Each case states the rule it pins
rather than just asserting a boolean, because a failure here should tell you
which rule moved.
"""

from __future__ import annotations

from agents.component.rules import Check, evaluate, failures, score, verdict

MCU = {
    "package": "LQFP-100", "footprint_id": "LQFP100_14X14_P050", "pin_count": 100,
    "vcc_min_v": 1.8, "vcc_max_v": 3.6, "temp_min_c": -40, "temp_max_c": 85,
    "max_freq_mhz": 168, "flash_kb": 1024, "ram_kb": 192, "io_count": 82,
    "interfaces": ["CAN", "SPI", "I2C", "USB_OTG"],
}


def only(checks, name):
    return next(c for c in checks if c.name == name)


class TestSupplyRail:
    def test_rail_inside_the_window_passes(self):
        assert verdict(evaluate(MCU, {"rail_voltage_v": 3.3})) == "PASS"

    def test_rail_above_the_window_fails(self):
        assert verdict(evaluate(MCU, {"rail_voltage_v": 5.0})) == "FAIL"

    def test_rail_below_the_window_fails(self):
        assert verdict(evaluate(MCU, {"rail_voltage_v": 1.2})) == "FAIL"

    def test_a_part_with_no_rail_recorded_cannot_pass(self):
        # Not specified is not the same as satisfied.
        assert verdict(evaluate({"package": "SOIC-8"}, {"rail_voltage_v": 3.3})) == "FAIL"


class TestTemperature:
    def test_part_must_reach_the_low_end(self):
        assert verdict(evaluate(MCU, {"ambient_temp_min_c": -40})) == "PASS"
        assert verdict(evaluate(MCU, {"ambient_temp_min_c": -55})) == "FAIL"

    def test_part_must_reach_the_high_end(self):
        assert verdict(evaluate(MCU, {"ambient_temp_max_c": 85})) == "PASS"
        assert verdict(evaluate(MCU, {"ambient_temp_max_c": 105})) == "FAIL"


class TestNumericBounds:
    def test_min_prefix_is_a_floor(self):
        assert verdict(evaluate(MCU, {"min_flash_kb": 512})) == "PASS"
        assert verdict(evaluate(MCU, {"min_flash_kb": 2048})) == "FAIL"

    def test_a_design_floor_is_checked_against_the_rated_ceiling(self):
        """
        min_freq_mhz has no freq_mhz to read on an MCU: the datasheet publishes
        max_freq_mhz, the rated maximum clock. The alias is what makes the rule
        mean anything, and without it every MCU candidate failed.
        """
        checks = evaluate(MCU, {"min_freq_mhz": 168})
        assert verdict(checks) == "PASS"
        assert only(checks, "max_freq_mhz").actual == "168"
        assert verdict(evaluate(MCU, {"min_freq_mhz": 180})) == "FAIL"

    def test_max_prefix_is_a_ceiling(self):
        assert verdict(evaluate(MCU, {"max_pin_count": 100})) == "PASS"
        assert verdict(evaluate(MCU, {"max_pin_count": 64})) == "FAIL"


class TestInterfaces:
    def test_every_listed_interface_must_be_present(self):
        assert verdict(evaluate(MCU, {"required_interfaces": ["CAN", "SPI"]})) == "PASS"

    def test_one_missing_interface_fails_and_is_named(self):
        checks = evaluate(MCU, {"required_interfaces": ["CAN", "ETHERNET"]})
        assert verdict(checks) == "FAIL"
        assert "ETHERNET" in only(checks, "interfaces").actual


class TestExactMatch:
    def test_footprint_must_match_exactly(self):
        assert verdict(evaluate(MCU, {"footprint_id": "LQFP100_14X14_P050"})) == "PASS"
        assert verdict(evaluate(MCU, {"footprint_id": "LQFP144_20X20_P050"})) == "FAIL"

    def test_an_unknown_key_is_an_exact_match_not_an_error(self):
        assert verdict(evaluate(MCU, {"package": "LQFP-100"})) == "PASS"
        assert verdict(evaluate(MCU, {"package": "UFBGA-169"})) == "FAIL"


class TestVerdictAndScore:
    def test_no_constraints_is_not_a_pass(self):
        """Nothing checked is not the same as everything satisfied."""
        assert verdict([]) == "FAIL"
        assert score([]) == 0

    def test_score_is_the_share_satisfied(self):
        checks = [Check("a", "x", "x", True), Check("b", "y", "z", False)]
        assert score(checks) == 50
        assert len(failures(checks)) == 1

    def test_one_failure_fails_the_whole_verdict(self):
        checks = evaluate(MCU, {"rail_voltage_v": 3.3, "min_flash_kb": 4096})
        assert verdict(checks) == "FAIL"
        assert score(checks) == 50
