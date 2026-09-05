"""
Reading articles with a hosted model on Groq.

Same interface as the other extractors, so nothing downstream changes.

Two things make this reliable enough to put in front of judges:

  * Constrained decoding. Groq takes our JSON schema and forces the model's
    output to match it. The category list goes in as an `enum`, so the model
    cannot emit a category that does not exist in our database. Tested: with
    the schema the model returns MCU / China / 2026-09-20; without it, the same
    model on the same article invents fields called `origin` and `products` and
    a category called `export_control`, none of which join to anything.

  * Backoff on 429. The free tier allows 8,000 tokens per minute and one event
    costs roughly 1,000, so a full seven-event run sits right on the ceiling.
    Rather than fail the run, wait and retry.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Tuple

import requests
from pydantic import BaseModel, Field

from .extract import SYSTEM_PROMPT, USER_TEMPLATE
from .local_extract import _clean, build_schema
from .schema import EVENT_TYPES, EventExtraction

BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_RETRIES = 4


class GroqExtractor:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str = None, timeout: int = 90):
        self.model = model
        self.timeout = timeout
        self._key = api_key or os.getenv("GROQ_API_KEY")
        if not self._key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Put it in the project .env file:\n"
                "    GROQ_API_KEY=gsk_...\n"
                "Do not hard-code it."
            )

    @property
    def name(self) -> str:
        return "groq:" + self.model

    # -- transport ---------------------------------------------------------

    def _chat(self, payload: Dict) -> Dict:
        headers = {
            "Authorization": "Bearer " + self._key,
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "temperature": 0, **payload}

        for attempt in range(MAX_RETRIES):
            response = requests.post(
                BASE_URL + "/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429 and attempt < MAX_RETRIES - 1:
                # Respect the server's own advice when it gives it.
                wait = float(response.headers.get("retry-after", 0)) or (4 * (attempt + 1))
                print(f"    rate limited, waiting {wait:.0f}s "
                      f"(attempt {attempt + 2} of {MAX_RETRIES})")
                time.sleep(wait)
                continue

            raise RuntimeError(
                f"Groq returned HTTP {response.status_code}: {response.text[:400]}"
            )

        raise RuntimeError("Groq stayed rate limited after several retries. Wait a minute and rerun.")

    # -- the interface -----------------------------------------------------

    def extract(self, event: Dict, categories: List[str]) -> Tuple[EventExtraction, str]:
        schema = build_schema(categories)
        schema["additionalProperties"] = False  # required by strict mode

        result = self._chat({
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "event_extraction", "schema": schema, "strict": True},
            },
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(
                        categories="\n".join("  - " + c for c in categories),
                        event_types="\n".join("  - " + e for e in EVENT_TYPES),
                    ),
                },
                {
                    "role": "user",
                    "content": USER_TEMPLATE.format(
                        source=event["source"],
                        source_type=event["source_type"],
                        published=event["published_at"],
                        headline=event["headline"],
                        body=event["body"] or "",
                    ),
                },
            ],
        })

        raw = json.loads(result["choices"][0]["message"]["content"])
        return EventExtraction(**_clean(raw, categories)), self.name

    def explain(self, system: str, facts: Dict) -> str:
        """
        gpt-oss models think before they answer, and that thinking is billed
        against max_tokens. At 400 the budget was being spent entirely on
        reasoning, and two of three explanations came back as empty strings.
        Give it room, and tell it not to think hard about a three-sentence
        summary in the first place.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(facts, default=str, indent=2)},
        ]

        for max_tokens, effort in ((1200, "low"), (3000, "medium")):
            result = self._chat({
                "max_tokens": max_tokens,
                "reasoning_effort": effort,
                "messages": messages,
            })
            text = (result["choices"][0]["message"].get("content") or "").strip()
            if text:
                return text

        return ""  # give up rather than fabricate; the caller shows the numbers anyway


# ── Part identification (used by the BOM intake, not by event analysis) ───────

PART_SYSTEM = """\
You identify electronic components from a bill-of-materials line.

You are given a part number and whatever description the document carried, plus
the exact list of component categories this company stocks.

Rules:
1. Decide which of the permitted categories this part belongs to. If it belongs
   to none of them, return "NONE" -- that is a useful answer, not a failure. It
   means the company does not stock this class of part at all.
2. Do not guess a category because it sounds adjacent. An operational amplifier
   is not a gate driver.
3. `equivalent_exists` asks whether a part of this class could substitute, not
   whether you found one. You are not shown the catalogue contents.
4. Keep `what_it_is` to one short sentence a buyer would understand.

Permitted categories:
{categories}
"""


class PartIdentification(BaseModel):
    category: str = Field(description="One of the permitted categories, or NONE")
    what_it_is: str = Field(description="One short sentence.")
    function: str = Field(description="Two or three words: what job it does on a board.")
    confidence: float = Field(description="0.0 to 1.0")


def identify_part(extractor: "GroqExtractor", mpn: str, description: str,
                  categories: List[str]) -> Dict:
    """Ask the model what an unmatched part number actually is."""
    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(categories) + ["NONE"]},
            "what_it_is": {"type": "string"},
            "function": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["category", "what_it_is", "function", "confidence"],
        "additionalProperties": False,
    }
    result = extractor._chat({
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "part_id", "schema": schema,
                                            "strict": True}},
        "messages": [
            {"role": "system",
             "content": PART_SYSTEM.format(
                 categories="\n".join("  - " + c for c in categories))},
            {"role": "user",
             "content": f"Part number: {mpn}\nDescription from the document: {description or '(none)'}"},
        ],
    })
    return json.loads(result["choices"][0]["message"]["content"])
