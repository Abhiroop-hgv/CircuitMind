"""
A third extractor: a model running locally through Ollama.

Same interface as LLMExtractor and FixtureExtractor, so nothing downstream
changes. Swapping the reader is a one-word flag.

The trick that makes a small local model workable here is CONSTRAINED DECODING.
Ollama accepts a JSON schema in `format` and forces the model's output to match
it, token by token. So instead of asking a 3B model nicely to use our category
names and hoping, we build the schema with our actual categories as an enum --
and the model is then physically unable to emit a category that does not exist
in our database. The vocabulary problem stops being a prompting problem.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

from .extract import SYSTEM_PROMPT, USER_TEMPLATE
from .schema import EVENT_TYPES, EventExtraction

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"


def build_schema(categories: List[str]) -> Dict:
    """
    The output contract, as JSON Schema, with our vocabulary baked in as enums.

    Written by hand rather than generated from the Pydantic model: small models
    are driven by a grammar compiled from this schema, and the anyOf/$ref shapes
    Pydantic emits for Optional fields make that grammar needlessly hard. Flat
    nullable types work far more reliably.
    """
    # The descriptions matter as much as the types: under constrained decoding
    # they are the only per-field instruction the model gets. Leaving them off
    # is what made the first live run return null for expected_delay_days on an
    # article that plainly said "four to eight weeks".
    return {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string", "enum": EVENT_TYPES,
                "description": "The kind of event this article reports.",
            },
            "affects_physical_supply": {
                "type": "boolean",
                "description": "True only if this could interrupt, delay or restrict the "
                               "physical movement or production of electronic components. "
                               "A price change or a demand forecast is not a physical "
                               "interruption.",
            },
            "countries": {
                "type": "array", "items": {"type": "string"},
                "description": "Countries whose outbound shipments or production are affected. "
                               "Full names, e.g. China, Taiwan, Japan.",
            },
            "cities": {
                "type": "array", "items": {"type": "string"},
                "description": "Cities or regions named in the article.",
            },
            "component_categories": {
                "type": "array",
                "items": {"type": "string", "enum": categories},
                "description": "Which of OUR component categories this could touch. Use only "
                               "the permitted values. Empty list if none apply.",
            },
            "materials": {
                "type": "array", "items": {"type": "string"},
                "description": "Raw materials named, e.g. copper, gallium, neon.",
            },
            "named_organisations": {
                "type": "array", "items": {"type": "string"},
                "description": "Companies or organisations named, verbatim.",
            },
            "hs_codes": {
                "type": "array", "items": {"type": "string"},
                "description": "Customs or HS codes mentioned, e.g. 8542.",
            },
            "effective_date": {
                "type": ["string", "null"],
                "description": "Date the restriction or disruption takes effect, as "
                               "YYYY-MM-DD. Null if the article does not state one.",
            },
            "expected_delay_days": {
                "type": ["integer", "null"],
                "description": "How many days of delay the article supports, as one number. "
                               "IF THE ARTICLE GIVES A RANGE, RETURN ITS MIDPOINT IN DAYS -- "
                               "'four to eight weeks' is 42, 'three to five days' is 4, "
                               "'20 weeks' is 140. Convert weeks to days by multiplying by 7. "
                               "Return null only when the article gives no timeframe at all.",
            },
            "mechanism": {
                "type": "string",
                "description": "One sentence: by what mechanism would this interrupt supply?",
            },
            "confidence": {
                "type": "number",
                "description": "0.0 to 1.0. Reserve values above 0.95 for articles that state "
                               "everything explicitly and leave nothing to interpretation.",
            },
            "reasoning": {
                "type": "string",
                "description": "At most two sentences explaining the classification.",
            },
        },
        "required": [
            "event_type", "affects_physical_supply", "countries", "cities",
            "component_categories", "materials", "named_organisations",
            "hs_codes", "effective_date", "expected_delay_days",
            "mechanism", "confidence", "reasoning",
        ],
    }


class OllamaExtractor:
    """Reads articles with a model running on this machine. No API key, no network."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        timeout: int = 600,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "ollama:" + self.model

    # -- helpers -----------------------------------------------------------

    def _post(self, path: str, payload: Dict) -> Dict:
        request = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"could not reach Ollama at {self.host}. Is it running? "
                f"Start it with `ollama serve`, or check `ollama list`. ({exc})"
            ) from exc

    def available_models(self) -> List[str]:
        with urllib.request.urlopen(self.host + "/api/tags", timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]

    # -- the interface -----------------------------------------------------

    def extract(self, event: Dict, categories: List[str]) -> Tuple[EventExtraction, str]:
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

        result = self._post(
            "/api/chat",
            {
                "model": self.model,
                "stream": False,
                "format": build_schema(categories),
                "options": {
                    # Extraction is not a creative task. Same article, same
                    # reading, every run -- which also keeps the demo stable.
                    "temperature": 0,
                    "num_ctx": 4096,
                },
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )

        raw = json.loads(result["message"]["content"])
        return EventExtraction(**_clean(raw, categories)), self.name

    def explain(self, system: str, facts: Dict) -> str:
        """Write the closing sentence with the same local model. No schema here."""
        result = self._post(
            "/api/chat",
            {
                "model": self.model,
                "stream": False,
                "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 220},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(facts, default=str, indent=2)},
                ],
            },
        )
        return result["message"]["content"].strip()


def _clean(raw: Dict, categories: List[str]) -> Dict:
    """
    Tidy up after a small model. The schema guarantees the SHAPE; it does not
    guarantee good sense, so a few cheap sanity rules here stop obvious nonsense
    reaching the matching step.
    """
    out = dict(raw)

    # Belt and braces -- the enum should already have prevented this.
    out["component_categories"] = [
        c for c in out.get("component_categories", []) if c in categories
    ]

    # Small models like to answer "several weeks" as a number they invented.
    delay = out.get("expected_delay_days")
    if isinstance(delay, (int, float)) and not (0 < delay <= 730):
        out["expected_delay_days"] = None

    confidence = out.get("confidence")
    if not isinstance(confidence, (int, float)):
        out["confidence"] = 0.5
    else:
        out["confidence"] = max(0.0, min(1.0, float(confidence)))

    date: Optional[str] = out.get("effective_date")
    if isinstance(date, str) and len(date) != 10:
        out["effective_date"] = None  # we want YYYY-MM-DD or nothing

    for key in ("countries", "cities", "materials", "named_organisations", "hs_codes"):
        out[key] = [str(v) for v in (out.get(key) or [])]

    for key in ("mechanism", "reasoning"):
        out[key] = str(out.get(key) or "")

    return out
