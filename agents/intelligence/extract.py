"""
Step 1 of the Intelligence Agent: article -> structured reading.

This is the ONLY place in the agent where a language model runs during analysis.
It is given the article and our controlled category vocabulary, and nothing else
-- no inventory, no supplier list, no quantities. It cannot invent facts about
our business because it is never shown any.

Two extractors implement the same interface:

  LLMExtractor      the real one. Claude, with a strict output schema.
  FixtureExtractor  hand-written readings, for testing the deterministic half
                    offline. Every row it produces is tagged so a fixture run
                    can never be mistaken for a model run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

from .schema import EVENT_TYPES, EventExtraction

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
You are the intelligence analyst for an electronics manufacturer's supply chain team.

You will be given one news article, government notice or regulatory announcement.
Your job is to read it and report what it says, in a structured form.

Rules you must follow:

1. Report only what the article states or clearly implies. Do not speculate about
   what might happen next, and do not predict future political events.
2. You know nothing about this company's suppliers, inventory or purchase orders,
   and you will not be told. Never name a supplier or a quantity that is not in
   the article itself.
3. For component_categories, use ONLY values from the permitted list below. These
   are the exact category names in our parts database. If the article concerns
   something we do not have a category for, return an empty list. Do not invent
   category names, and do not translate a category into a similar-sounding one.
4. If the article gives no basis for a number, return null rather than guessing.

Permitted component_categories values:
{categories}

Permitted event_type values:
{event_types}

Map the article's own language onto the permitted categories. For example, a
notice about "microcontrollers" or "MCUs" maps to MCU; one about "multilayer
ceramic capacitors" or "MLCCs" maps to CAPACITOR_MLCC. A notice about a category
that is not on the list maps to nothing -- return an empty list.\
"""

USER_TEMPLATE = """\
Source: {source} ({source_type})
Published: {published}

Headline: {headline}

Body:
{body}\
"""


class LLMExtractor:
    """Structured extraction via the Anthropic API."""

    name = "llm:" + MODEL

    def __init__(self, client=None):
        if client is None:
            import anthropic  # imported lazily so offline runs need no SDK

            client = anthropic.Anthropic()
        self._client = client

    def extract(self, event: Dict, categories: list) -> Tuple[EventExtraction, str]:
        system = SYSTEM_PROMPT.format(
            categories="\n".join("  - " + c for c in categories),
            event_types="\n".join("  - " + e for e in EVENT_TYPES),
        )
        user = USER_TEMPLATE.format(
            source=event["source"],
            source_type=event["source_type"],
            published=event["published_at"],
            headline=event["headline"],
            body=event["body"] or "",
        )

        response = self._client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=EventExtraction,
        )
        return response.parsed_output, self.name


class FixtureExtractor:
    """
    Hand-written readings of the seeded events, used ONLY to exercise the
    matching and scoring code without burning API calls.

    These are test fixtures, not a shortcut for the demo. Nothing here is
    derived from our database -- each fixture contains exactly what a careful
    reader would take from the article text, which is all the real extractor
    is allowed to produce either. Rows written from a fixture run carry
    extractor = 'fixture', so a demo cannot silently run on them.
    """

    name = "fixture"

    def __init__(self, path: Optional[Path] = None):
        path = path or Path(__file__).parent / "fixtures" / "extractions.json"
        self._data = json.loads(path.read_text(encoding="utf-8"))

    def extract(self, event: Dict, categories: list) -> Tuple[EventExtraction, str]:
        key = event["external_id"]
        if key not in self._data:
            raise KeyError(
                f"no fixture for event {key}. Fixtures cover only the seeded demo "
                f"events; use the LLM extractor for anything else."
            )
        raw = dict(self._data[key])

        # Enforce the same vocabulary rule the model is held to, so a stale
        # fixture cannot smuggle in a category that does not exist.
        unknown = [c for c in raw["component_categories"] if c not in categories]
        if unknown:
            raise ValueError(f"fixture {key} uses unknown categories: {unknown}")

        return EventExtraction(**raw), self.name
