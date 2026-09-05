"""
Ask the assistant a question from the command line.

    python scripts/ask.py "how much of the STM32F407VGT6 is left?"
    python scripts/ask.py --show "what news affects my inventory?"

--show prints the tools it called and what came back, which is the thing worth
looking at: the answer is only as good as the calls underneath it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agents.assistant.agent import Assistant, AssistantError   # noqa: E402
from db.connection import connect_readonly                     # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:]]
    show = "--show" in args
    args = [a for a in args if a != "--show"]

    if not args:
        print(__doc__)
        return 1

    question = " ".join(args)
    conn = connect_readonly()
    try:
        assistant = Assistant(conn, verbose=show)
        out = assistant.ask(question)
    except AssistantError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        conn.close()

    if show:
        for c in out["calls"]:
            print(f"\n  {c['tool']}({json.dumps(c['arguments'])})")
            print("  " + json.dumps(c["result"], default=str)[:600])
        print()

    print(out["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
