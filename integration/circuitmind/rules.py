"""
The deterministic compatibility gate.

This file decides whether a part can go on a board. No model, no embeddings, no
similarity score -- those find candidates, they do not get a vote on the answer.
Two datasheets can read almost identically and differ by a package that will not
sit on the footprint.

Everything is checked against `bom.design_constraints` -- what the BOARD needs --
not against the incumbent part's datasheet. Those are different things. The same
STM32F407VGT6 is held to 85 C and 78 I/O on the MC-3000 and to 70 C and 70 I/O
on the SD-220, so a candidate can be valid for one board and not the other.

Constraint keys are interpreted by naming convention, so adding a new constraint
to the BOM needs no code change here:

    min_<field>          spec[field] >= value
    max_<field>          spec[field] <= value
    rail_voltage_v       spec.vcc_min_v <= value <= spec.vcc_max_v
    ambient_temp_min_c   spec.temp_min_c <= value
    ambient_temp_max_c   spec.temp_max_c >= value
    required_interfaces  every listed interface present in spec.interfaces
    <anything else>      spec[key] must equal value exactly
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Check:
    name: str
    required: str
    actual: str
    ok: bool

    def __str__(self) -> str:
        return f"{'ok  ' if self.ok else 'FAIL'} {self.name}: need {self.required}, has {self.actual}"


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lookup(spec: Dict, field: str, bound_prefix: str):
    """
    Find the spec field a constraint refers to, allowing for the fact that a
    board's floor is usually checked against a part's ceiling and vice versa.

    A design needing `min_freq_mhz: 160` must be compared against the part's
    `max_freq_mhz` -- its rated maximum clock -- because that is the number a
    datasheet actually publishes. Same shape for a design ceiling against a
    part's rated minimum. The plain field always wins when it exists, so
    `freq_mhz: 25.0` on a crystal still matches exactly.
    """
    if field in spec:
        return field, spec[field]
    alias = bound_prefix + field
    if alias in spec:
        return alias, spec[alias]
    return field, None


def evaluate(spec: Dict, constraints: Dict) -> List[Check]:
    """Run every constraint against one candidate's spec sheet."""
    checks: List[Check] = []

    for key, want in constraints.items():
        # -- supply rail must sit inside the part's operating window ---------
        if key == "rail_voltage_v":
            lo, hi = _num(spec.get("vcc_min_v")), _num(spec.get("vcc_max_v"))
            rail = _num(want)
            ok = lo is not None and hi is not None and rail is not None and lo <= rail <= hi
            checks.append(Check("supply rail", f"{want} V works",
                                f"{lo}-{hi} V" if lo is not None else "not specified", ok))

        # -- the part must cover the board's ambient range -------------------
        elif key == "ambient_temp_min_c":
            have = _num(spec.get("temp_min_c"))
            ok = have is not None and have <= _num(want)
            checks.append(Check("temp, low end", f"<= {want} C",
                                f"{have} C" if have is not None else "not specified", ok))

        elif key == "ambient_temp_max_c":
            have = _num(spec.get("temp_max_c"))
            ok = have is not None and have >= _num(want)
            checks.append(Check("temp, high end", f">= {want} C",
                                f"{have} C" if have is not None else "not specified", ok))

        # -- peripherals the design actually uses ----------------------------
        elif key == "required_interfaces":
            have = set(spec.get("interfaces") or [])
            missing = [i for i in want if i not in have]
            checks.append(Check("interfaces", ", ".join(want),
                                "missing " + ", ".join(missing) if missing else "all present",
                                not missing))

        # -- numeric floors and ceilings -------------------------------------
        elif key.startswith("min_"):
            field, raw = _lookup(spec, key[4:], "max_")
            have = _num(raw)
            ok = have is not None and have >= _num(want)
            checks.append(Check(field, f">= {want}",
                                str(raw) if raw is not None else "not specified", ok))

        elif key.startswith("max_"):
            field, raw = _lookup(spec, key[4:], "min_")
            have = _num(raw)
            ok = have is not None and have <= _num(want)
            checks.append(Check(field, f"<= {want}",
                                str(raw) if raw is not None else "not specified", ok))

        # -- everything else is an exact match --------------------------------
        else:
            have = spec.get(key)
            ok = have is not None and str(have) == str(want)
            checks.append(Check(key, str(want), str(have) if have is not None else "not specified", ok))

    return checks


def verdict(checks: List[Check]) -> str:
    return "PASS" if checks and all(c.ok for c in checks) else "FAIL"


def score(checks: List[Check]) -> int:
    """
    Percentage of checks satisfied. Only 100 counts as usable -- the number
    exists so a near miss can be told apart from a part that fails everything,
    which is useful when nothing passes and an engineer has to pick the least
    bad option to look at by hand.
    """
    if not checks:
        return 0
    return round(100 * sum(1 for c in checks if c.ok) / len(checks))


def failures(checks: List[Check]) -> List[Check]:
    return [c for c in checks if not c.ok]
