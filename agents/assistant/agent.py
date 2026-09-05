"""
The assistant: a question in English, an answer built only from tools.

This is not retrieval-augmented generation, though it is often called that.
Nothing is embedded and no text is stuffed into the prompt hoping the model
reads it correctly. The model's only job is to choose which question to ask of
the database; the answer comes back as data and the model reports it.

That choice is what keeps the demo honest. The rule the whole project runs on
is that the model may not invent inventory quantities, prices or lead times.
Here the model is never in a position to: it has no numbers until a tool hands
it some, and every tool is a SELECT against the same tables the dashboard reads.

The loop is the standard one. Ask, and if the reply contains tool calls, run
them, append the results, and ask again. Stop when the model answers in prose
or when the round limit is hit.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

import requests

from .guard import check as guard_check
from .tools import REGISTRY, SCHEMAS

BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_RETRIES = 4
MAX_ROUNDS = 6

SYSTEM_PROMPT = """\
You are the supply-chain assistant for a company that builds electronic boards.
You answer questions about that company's own inventory, demand and supply risk.

Rules you must follow:

1. Never state a quantity, price, date or part number that did not come back
   from a tool in this conversation. You have no knowledge of this company's
   stock. If you have not called a tool, you do not know the answer.
2. If a tool returns an error or says no analysis has been run, say exactly
   that. Do not estimate, and do not substitute a number from another part.
3. If a tool returns candidates because the part was ambiguous, ask the user
   which one they mean instead of picking.
4. Answer in plain English, briefly. The reader is a planner, not an engineer.
   Give the number first, then one line of context if it helps.
5. When a number is derived, show the arithmetic the tool gave you rather than
   asserting the result on your own authority.
6. Never call the same tool twice with the same arguments. The answer will not
   change, and the wait is the user's.

You cannot approve anything, place an order, or change any record. If asked to,
say that approval is a human decision made in the dashboard.
"""


class AssistantError(RuntimeError):
    pass


class Assistant:
    def __init__(self, conn, model: str = DEFAULT_MODEL, api_key: Optional[str] = None,
                 timeout: int = 90, verbose: bool = False):
        self.conn = conn
        self.model = model
        self.timeout = timeout
        self.verbose = verbose
        self._key = api_key or os.getenv("GROQ_API_KEY")
        if not self._key:
            raise AssistantError(
                "GROQ_API_KEY is not set. Put it in the project .env file:\n"
                "    GROQ_API_KEY=gsk_...")

    # -- transport ---------------------------------------------------------

    def _chat(self, messages: List[Dict]) -> Dict:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "tools": SCHEMAS,
            "tool_choice": "auto",
            # gpt-oss spends tokens on reasoning before it writes; too small a
            # ceiling returns an empty message with the answer never emitted.
            "max_tokens": 1600,
            "reasoning_effort": "low",
        }
        headers = {"Authorization": "Bearer " + self._key,
                   "Content-Type": "application/json"}

        for attempt in range(MAX_RETRIES):
            r = requests.post(BASE_URL + "/chat/completions", headers=headers,
                              json=payload, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 and attempt < MAX_RETRIES - 1:
                wait = float(r.headers.get("retry-after", 0)) or (4 * (attempt + 1))
                if self.verbose:
                    print(f"    rate limited, waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            raise AssistantError(f"Groq returned {r.status_code}: {r.text[:300]}")
        raise AssistantError("Groq rate limit did not clear")

    # -- tools -------------------------------------------------------------

    def _run_tool(self, name: str, args: Dict, seen: Dict) -> Dict:
        # The model sometimes asks for the same thing twice in consecutive
        # rounds. Answering from what we already fetched keeps the database out
        # of it; the wasted round is discouraged in the prompt instead.
        key = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if key in seen:
            return seen[key]

        fn = REGISTRY.get(name)
        if fn is None:
            # The model asked for something that does not exist. Say so rather
            # than failing the turn; it will usually pick a real tool next.
            return {"error": f"no such tool: {name}"}
        try:
            out = fn(self.conn, **args)
        except TypeError as exc:
            out = {"error": f"bad arguments for {name}: {exc}"}
        except Exception as exc:                       # noqa: BLE001
            out = {"error": f"{name} failed: {exc}"}

        seen[key] = out
        return out

    # -- the loop ----------------------------------------------------------

    def ask(self, question: str) -> Dict:
        """
        Returns {"answer", "calls", "unverified"}.

        The calls are returned as well as the answer so the interface can show
        its working. A recommendation nobody can audit is not worth much, and
        the same applies to an answer.
        """
        messages: List[Dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        calls: List[Dict] = []
        seen: Dict[str, Dict] = {}

        for _ in range(MAX_ROUNDS):
            reply = self._chat(messages)["choices"][0]["message"]
            tool_calls = reply.get("tool_calls") or []

            if not tool_calls:
                answer = (reply.get("content") or "").strip()
                if not answer:
                    answer = ("I could not put that into words. The tool results "
                              "are shown below.")
                # Nothing reaches the caller unchecked.
                answer, unverified = guard_check(answer, calls, question)
                return {"answer": answer, "calls": calls, "unverified": unverified}

            messages.append({
                "role": "assistant",
                "content": reply.get("content") or "",
                "tool_calls": tool_calls,
            })

            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                if self.verbose:
                    print(f"    -> {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})")

                result = self._run_tool(name, args, seen)
                calls.append({"tool": name, "arguments": args, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, default=str),
                })

        return {"answer": "I could not settle on an answer within the round limit.",
                "calls": calls, "unverified": []}
