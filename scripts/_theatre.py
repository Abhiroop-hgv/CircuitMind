"""Shared presentation helpers for the demo scenarios."""

from __future__ import annotations

import time

WIDTH = 78
WATCH_MPN = "STM32F407VGT6"


def act(n: int, title: str, subtitle: str = "") -> None:
    print()
    print("━" * WIDTH)
    print(f"  ACT {n}   {title}")
    if subtitle:
        print(f"          {subtitle}")
    print("━" * WIDTH)
    print()


def beat(pause: bool) -> None:
    if pause:
        try:
            input("\n        [enter to continue]")
        except (EOFError, KeyboardInterrupt):
            pass
    else:
        time.sleep(0.4)


def wrap(text: str, width: int):
    words, line, out = (text or "").split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out
