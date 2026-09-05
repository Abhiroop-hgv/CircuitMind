"""
The check that runs after the model answers, before anyone sees it.

Until now the promise "it will not invent your numbers" rested on the system
prompt -- instructions to a model, which is persuasion, not enforcement. This
module makes part of it mechanical.

Two rules, deliberately different in strength:

  BLOCK   The model answered with a figure in it and called no tool at all.
          There is no legitimate way to know this company's numbers without
          asking the database, so the answer is replaced rather than shown.

  FLAG    A tool was called, but the answer contains a figure that appears in
          no tool result. Usually innocent -- the model worked out a percentage
          or a difference -- so this annotates rather than suppresses. Silently
          hiding a real answer would be worse than showing a caution next to it.

Numbers inside part codes are ignored. STM32F407VGT6 is a name, not a figure,
and treating the 407 in it as a claim would flag every honest answer.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Tuple

# A run of digits that is not glued to a letter, so part codes are skipped, with
# optional thousands separators. The model uses ordinary spaces, non-breaking
# spaces and narrow no-break spaces for those, depending on its mood.
SEPARATORS = ",    "
NUMBER = re.compile(
    r"(?<![A-Za-z0-9])"
    r"\d+(?:[" + SEPARATORS + r"]\d{3})*(?:\.\d+)?"
    r"(?![A-Za-z0-9])"
)

REFUSAL = (
    "I stopped that answer. It contained figures but I did not look anything up, "
    "and I am not allowed to state this company's numbers from memory. Ask again "
    "naming the part, or ask about stock, shortages, forecasts, suppliers, events "
    "or pending approvals."
)


def _numbers(text: str) -> List[str]:
    """Every figure in a piece of text, as written."""
    return NUMBER.findall(text or "")


def _value(raw: str) -> float | None:
    cleaned = raw
    for ch in SEPARATORS:
        cleaned = cleaned.replace(ch, "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _known_values(calls: List[Dict]) -> set:
    """
    Every figure the database actually returned.

    Both the results and the arguments count: if the user asked about 2026-09
    and the model repeats it, that came from the conversation, not from thin
    air. Rounded forms are admitted too, since a tool returning 0.529 and an
    answer saying 0.53 are the same claim.
    """
    known = set()
    for call in calls:
        blob = json.dumps(call.get("result"), default=str) + " " + \
               json.dumps(call.get("arguments"), default=str)
        for raw in _numbers(blob):
            v = _value(raw)
            if v is None:
                continue
            known.add(v)
            known.add(round(v))
            known.add(round(v, 1))
            known.add(round(v, 2))
    return known


def check(answer: str, calls: List[Dict], question: str = "") -> Tuple[str, List[str]]:
    """
    Returns the answer to show, and any figures that could not be traced.

    The answer is replaced entirely when the block rule fires; otherwise it is
    returned untouched and the caller decides how loudly to mention the flags.
    """
    figures = _numbers(answer)

    if not figures:
        return answer, []

    if not calls:
        return REFUSAL, []

    known = _known_values(calls)
    # Figures the user themselves supplied are not inventions either.
    for raw in _numbers(question):
        v = _value(raw)
        if v is not None:
            known.add(v)
            known.add(round(v))

    unverified = []
    for raw in figures:
        v = _value(raw)
        if v is None:
            continue
        if v in known or round(v) in known or round(v, 1) in known or round(v, 2) in known:
            continue
        unverified.append(raw)

    # Preserve order, drop repeats.
    seen, ordered = set(), []
    for u in unverified:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return answer, ordered
