"""
Values the whole API agrees on.

TODAY is pinned rather than read from the clock: the seeded data describes a
specific week, and a demo that silently means something different tomorrow is
not a demo. Change it here, not in five places.
"""

from __future__ import annotations

from datetime import date

TODAY = date(2026, 9, 3)
WATCH_MPN = "STM32F407VGT6"
