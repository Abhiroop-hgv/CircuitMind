"""
A drop-in replacement for CircuitMind's `compatibility_score()`.

WHY
---
CircuitMind's current implementation takes the spec arguments and discards them:

    def compatibility_score(*, semantic, target_package=None, cand_package=None,
                            target_pins=None, cand_pins=None, ...) -> float:
        return round(max(0.0, min(1.0, semantic)), 4)

The comment says footprint, pinout and voltage are "enforced as hard filters
upstream", but the upstream SQL filters only category and voltage overlap. So
package and pin count are passed in and checked nowhere. The call site in
`alternate_match.py` looks like it is doing careful spec work; it is ranking on
description text alone.

This version keeps the signature and the contract -- a float in [0, 1] that the
existing `c >= threshold` comparison still works with -- and adds the check.

WHAT CHANGES
------------
A candidate that cannot physically go on the board scores 0.0 and therefore
falls below any threshold. Everything else keeps its semantic score, so ranking
among genuinely valid candidates is unchanged. The vector search still decides
WHICH candidates to consider; this only decides which of them are permissible.

ON PACKAGE
----------
CircuitMind's note that "a drop-in replacement frequently comes in a different
package" is true when you are buying a part, and false when you are populating
a board that is already laid out: a different package does not sit on the
footprint. Both readings are legitimate, so `strict_package` selects between
them. It defaults to True, because the caller is choosing a substitute for an
existing BOM line.

USING IT
--------
    from .compatibility import compatibility_score      # same call, same shape

`rules.py` sits beside this file and has no dependencies beyond the standard
library. `compatibility_verdict()` returns the reasons as well as the number,
which is what a screen should show: "rejected -- needs LQFP-100, has UFBGA-169"
is worth more to an engineer than 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .rules import Check, evaluate, failures, verdict as rule_verdict


@dataclass
class Verdict:
    """The number the caller wanted, plus why."""
    score: float
    passed: bool
    semantic: float
    checks: List[Check] = field(default_factory=list)

    @property
    def reasons(self) -> List[str]:
        return [f"needs {c.name} {c.required}, has {c.actual}" for c in failures(self.checks)]

    def __str__(self) -> str:
        if self.passed:
            return f"PASS ({self.score:.4f})"
        return "REJECTED -- " + "; ".join(self.reasons)


def _candidate_spec(package: Optional[str], pins: Optional[int],
                    vmin: Optional[float], vmax: Optional[float],
                    extra: Optional[Dict] = None) -> Dict:
    """
    CircuitMind's component columns in the shape the rule engine reads.

    Named to match the constraint vocabulary: a supply window is vcc_min_v to
    vcc_max_v, which is what a datasheet prints.
    """
    spec: Dict = {}
    if package is not None:
        spec["package"] = package
    if pins is not None:
        spec["pin_count"] = pins
    if vmin is not None:
        spec["vcc_min_v"] = vmin
    if vmax is not None:
        spec["vcc_max_v"] = vmax
    if extra:
        spec.update(extra)
    return spec


def _requirements(package: Optional[str], pins: Optional[int],
                  vmin: Optional[float], vmax: Optional[float],
                  strict_package: bool) -> Dict:
    """
    What the incumbent part demands of anything replacing it.

    A constraint is only added when the target value is known. An unknown
    requirement is not a requirement -- inventing one would reject candidates
    for a spec nobody recorded, which is worse than not checking it.
    """
    want: Dict = {}
    if strict_package and package is not None:
        want["package"] = package
        if pins is not None:
            want["pin_count"] = pins

    # The candidate's supply window must cover the incumbent's, at both ends.
    # Written with the rule engine's own prefixes so no new rule type is needed.
    if vmin is not None:
        want["max_vcc_min_v"] = vmin
    if vmax is not None:
        want["min_vcc_max_v"] = vmax
    return want


def compatibility_verdict(
    *,
    semantic: float,
    target_package: Optional[str] = None, cand_package: Optional[str] = None,
    target_pins: Optional[int] = None, cand_pins: Optional[int] = None,
    target_vmin: Optional[float] = None, target_vmax: Optional[float] = None,
    cand_vmin: Optional[float] = None, cand_vmax: Optional[float] = None,
    strict_package: bool = True,
    engineer_constraints: Optional[Dict] = None,
    candidate_spec: Optional[Dict] = None,
) -> Verdict:
    """
    Score a candidate, and say what it failed on.

    `engineer_constraints` is the payload from `constraint_gate` -- the values a
    human typed before matching ran. They are merged in as ordinary constraints,
    so a gate answer of {"rail_voltage_v": 3.3} is enforced by the same code
    path as everything else rather than by a special case.

    `candidate_spec` carries any further datasheet fields already known, for
    those constraints to be checked against.
    """
    spec = _candidate_spec(cand_package, cand_pins, cand_vmin, cand_vmax, candidate_spec)
    constraints = _requirements(target_package, target_pins,
                                target_vmin, target_vmax, strict_package)
    if engineer_constraints:
        constraints.update(engineer_constraints)

    checks = evaluate(spec, constraints) if constraints else []
    # No constraints recorded means nothing to fail; fall back to the semantic
    # score rather than passing a candidate off as verified.
    passed = rule_verdict(checks) == "PASS" if checks else True

    clamped = round(max(0.0, min(1.0, float(semantic))), 4)
    return Verdict(score=clamped if passed else 0.0, passed=passed,
                   semantic=clamped, checks=checks)


def compatibility_score(
    *,
    semantic: float,
    target_package: Optional[str] = None, cand_package: Optional[str] = None,
    target_pins: Optional[int] = None, cand_pins: Optional[int] = None,
    target_vmin: Optional[float] = None, target_vmax: Optional[float] = None,
    cand_vmin: Optional[float] = None, cand_vmax: Optional[float] = None,
    strict_package: bool = True,
    engineer_constraints: Optional[Dict] = None,
    candidate_spec: Optional[Dict] = None,
) -> float:
    """
    Same signature and return type as the function it replaces.

    A candidate that fails a hard constraint returns 0.0, so the existing
    `c >= threshold` filter in alternate_match.py drops it with no change
    needed there.
    """
    return compatibility_verdict(
        semantic=semantic,
        target_package=target_package, cand_package=cand_package,
        target_pins=target_pins, cand_pins=cand_pins,
        target_vmin=target_vmin, target_vmax=target_vmax,
        cand_vmin=cand_vmin, cand_vmax=cand_vmax,
        strict_package=strict_package,
        engineer_constraints=engineer_constraints,
        candidate_spec=candidate_spec,
    ).score
