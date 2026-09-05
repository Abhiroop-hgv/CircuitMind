# Compatibility gate for CircuitMind

A drop-in replacement for `compatibility_score()` in
`services/backend/app/docai/vector_search.py`.

## The problem it fixes

The current implementation accepts the spec arguments and ignores them:

```python
def compatibility_score(*, semantic, target_package=None, cand_package=None,
                        target_pins=None, cand_pins=None, ...) -> float:
    return round(max(0.0, min(1.0, semantic)), 4)
```

The comment says footprint, pinout and voltage are enforced as hard filters
upstream. The upstream SQL filters `category` and voltage overlap only, so
**package and pin count are passed in and checked nowhere**. `alternate_match.py`
builds a careful-looking call with package, pins and voltage — and ranks on
description text alone.

Two parts can read almost identically and differ by a package that will not sit
on the footprint. `STM32F429ZIT6` scores 0.98 against `STM32F407VGT6` and is
LQFP-144 against LQFP-100.

## What changes

A candidate that cannot physically go on the board returns **0.0**, so the
existing `c >= threshold` filter drops it with no change at the call site.
Everything else keeps its semantic score, so ranking among valid candidates is
untouched.

The vector search still decides *which* candidates to consider. This decides
which of them are permissible.

| candidate | before | after |
|---|---|---|
| same package, same pins, same rail | 0.97 | 0.97 |
| LQFP-144 instead of LQFP-100 | 0.98 | **0.0** |
| UFBGA-169, identical electricals | 0.96 | **0.0** |
| rail does not reach 1.8 V | 0.95 | **0.0** |
| nothing recorded about the incumbent | 0.88 | 0.88 |

That last row matters: with no recorded requirement there is nothing to check,
and it returns the semantic score rather than passing the candidate off as
verified.

## Installing

Copy `rules.py` and `compatibility.py` into `services/backend/app/docai/`.
Both are standard library only — no torch, no pgvector, no new dependency.

In `vector_search.py`, delete the old `compatibility_score` and re-export:

```python
from .compatibility import compatibility_score, compatibility_verdict  # noqa: F401
```

`alternate_match.py` needs no change. Its existing call already passes every
argument this uses.

## Two things to decide

**1. `strict_package` (defaults to True).** Your note that "a drop-in
replacement frequently comes in a different package/pin count" is right when
buying a part and wrong when populating a board already laid out. Pass
`strict_package=False` for a purchasing search; leave it True when substituting
an existing BOM line.

**2. Wire up the constraint gate.** The values an engineer types at
`constraint_gate` can be passed straight through:

```python
compat = compatibility_score(semantic=float(m.similarity),
                             ..., engineer_constraints=state["value_constraints"])
```

They are then enforced by the same code path as everything else, rather than
by a separate special case. Constraint keys are read by naming convention, so
new ones need no code change:

```
min_<field>          spec[field] >= value
max_<field>          spec[field] <= value
rail_voltage_v       spec.vcc_min_v <= value <= spec.vcc_max_v
ambient_temp_min_c   spec.temp_min_c <= value
required_interfaces  every listed interface present in spec.interfaces
<anything else>      exact match
```

## Showing the reason

`compatibility_verdict()` returns the same score plus the failed checks:

```
REJECTED -- needs package LQFP-100, has LQFP-144; needs pin_count 100, has 144
```

Worth surfacing in the UI. "Rejected, needs LQFP-100" is more use to an
engineer than a 0.0.

## Tests

```
python integration/circuitmind/test_compatibility.py
```

Eight cases, each one a candidate the description-only score would have
accepted.
