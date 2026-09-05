"""
What the replacement changes, shown against the function it replaces.

Each case is a candidate the description-only score would have accepted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from integration.circuitmind.compatibility import compatibility_score, compatibility_verdict

# The incumbent: STM32F407VGT6, LQFP-100, 100 pins, 1.8-3.6 V.
TARGET = dict(target_package="LQFP-100", target_pins=100,
              target_vmin=1.8, target_vmax=3.6)

CASES = [
    ("STM32F429VGT6  same package, same pins, same rail",
     dict(semantic=0.97, cand_package="LQFP-100", cand_pins=100,
          cand_vmin=1.8, cand_vmax=3.6), True),

    ("STM32F429ZIT6  reads almost identically, LQFP-144",
     dict(semantic=0.98, cand_package="LQFP-144", cand_pins=144,
          cand_vmin=1.8, cand_vmax=3.6), False),

    ("BGA part       same electricals, will not sit on the footprint",
     dict(semantic=0.96, cand_package="UFBGA-169", cand_pins=169,
          cand_vmin=1.8, cand_vmax=3.6), False),

    ("5 V-only part  package fits, rail does not reach 1.8 V",
     dict(semantic=0.95, cand_package="LQFP-100", cand_pins=100,
          cand_vmin=3.0, cand_vmax=5.5), False),

    ("same part, package rule relaxed for a purchasing search",
     dict(semantic=0.98, cand_package="LQFP-144", cand_pins=144,
          cand_vmin=1.8, cand_vmax=3.6, strict_package=False), True),

    ("engineer typed rail_voltage_v 3.3 at the constraint gate",
     dict(semantic=0.99, cand_package="LQFP-100", cand_pins=100,
          cand_vmin=1.8, cand_vmax=3.6,
          engineer_constraints={"rail_voltage_v": 3.3},
          candidate_spec={"vcc_min_v": 1.8, "vcc_max_v": 3.6}), True),

    ("same gate constraint, candidate cannot run at 3.3 V",
     dict(semantic=0.99, cand_package="LQFP-100", cand_pins=100,
          cand_vmin=4.5, cand_vmax=5.5,
          engineer_constraints={"rail_voltage_v": 3.3},
          candidate_spec={"vcc_min_v": 4.5, "vcc_max_v": 5.5}), False),

    ("nothing recorded about the incumbent -- cannot check, does not pretend to",
     dict(semantic=0.88, cand_package="LQFP-100", cand_pins=100), True),
]


def main() -> int:
    bad = 0
    for label, kwargs, expect_pass in CASES:
        args = dict(TARGET)
        if "nothing recorded" in label:
            args = {}
        args.update(kwargs)

        v = compatibility_verdict(**args)
        old = round(max(0.0, min(1.0, kwargs["semantic"])), 4)   # what it used to return
        ok = v.passed is expect_pass
        bad += 0 if ok else 1

        print(f"  {'ok ' if ok else 'BAD'}  {label}")
        print(f"        was {old}  ->  now {v.score}   {v}")

    print(f"\n  {len(CASES) - bad} of {len(CASES)} as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
