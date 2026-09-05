"""
The contract between the language half of the Intelligence Agent and the
deterministic half.

The LLM fills this in from a news article and nothing else. Note what is NOT
here: no quantities of ours, no supplier names of ours, no risk level. The model
reports what the article says; our code decides what it means for us.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

EVENT_TYPES = [
    "EXPORT_RESTRICTION",
    "IMPORT_RESTRICTION",
    "TARIFF",
    "REGULATION",
    "NATURAL_DISASTER",
    "PORT_DISRUPTION",
    "FACTORY_INCIDENT",
    "SUPPLIER_NEWS",
    "PRICE_MOVE",
    "DEMAND_NEWS",
    "OTHER",
]


class EventExtraction(BaseModel):
    """A structured reading of one external event."""

    event_type: str = Field(
        description="One of: " + ", ".join(EVENT_TYPES)
    )
    affects_physical_supply: bool = Field(
        description=(
            "True only if this event could plausibly interrupt, delay or restrict the "
            "physical movement or production of electronic components. A price move or "
            "a demand forecast is NOT a physical supply interruption."
        )
    )
    countries: List[str] = Field(
        description="Countries whose outbound shipments or production this affects. Full names, e.g. China, Taiwan, Japan."
    )
    cities: List[str] = Field(description="Cities or regions named, if any.")
    component_categories: List[str] = Field(
        description=(
            "Which of OUR component categories this could touch. You will be given the "
            "exact list of permitted values. Use ONLY values from that list. Return an "
            "empty list if none of them apply."
        )
    )
    materials: List[str] = Field(description="Raw materials named, e.g. copper, neon, gallium.")
    named_organisations: List[str] = Field(
        description="Companies or organisations named in the article, verbatim."
    )
    hs_codes: List[str] = Field(description="Customs / HS codes mentioned, e.g. 8542.")
    effective_date: Optional[str] = Field(
        description="Date the restriction or disruption takes effect, YYYY-MM-DD. Null if not stated."
    )
    expected_delay_days: Optional[int] = Field(
        description=(
            "Delay in days that the article itself supports, as a single number. "
            "Take the midpoint of any range the article gives. Null if the article "
            "gives no basis for a number -- do not guess."
        )
    )
    mechanism: str = Field(
        description="One sentence: by what mechanism would this interrupt supply?"
    )
    confidence: float = Field(
        description="0.0 to 1.0 -- how confident you are in this reading of the article."
    )
    reasoning: str = Field(
        description="Two sentences at most, explaining the classification."
    )
