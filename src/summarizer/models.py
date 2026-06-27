"""``Summary`` output models (CONTRACTS §5).

The LLM produces the *content* fields (``one_liner``, ``sections`` with ``Bullet``s carrying
``source_refs``); the pipeline fills in the *meta* fields (``model`` / ``generated_at`` /
token+cost usage / ``faithfulness``). Keeping them on one model lets the UI and eval read everything
in one place.

Fixed sections, in this order: Problems, Medications, Recent Encounters, Key Results, Allergies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from clinical_core.eval.faithfulness import FaithfulnessReport
from clinical_core.fhir.models import SourceRef

SECTION_ORDER = ["Problems", "Medications", "Recent Encounters", "Key Results", "Allergies"]


class Bullet(BaseModel):
    text: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class Section(BaseModel):
    heading: str
    bullets: list[Bullet] = Field(default_factory=list)
    no_data: bool = False

    @model_validator(mode="after")
    def _no_data_implies_empty(self) -> Section:
        if self.no_data and self.bullets:
            raise ValueError(f"Section '{self.heading}' flagged no_data but has bullets")
        return self


class SummaryContent(BaseModel):
    """The structured payload the LLM returns (no meta)."""

    one_liner: str
    sections: list[Section]

    @model_validator(mode="after")
    def _ordered_and_complete(self) -> SummaryContent:
        headings = [s.heading for s in self.sections]
        if headings != SECTION_ORDER:
            raise ValueError(f"sections must be exactly {SECTION_ORDER} in order; got {headings}")
        return self


class Summary(BaseModel):
    patient_id: str
    one_liner: str
    sections: list[Section]
    model: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    faithfulness: FaithfulnessReport | None = None  # set by Phase 3 guardrail

    @classmethod
    def from_content(
        cls,
        content: SummaryContent,
        *,
        patient_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        faithfulness: Any | None = None,
    ) -> Summary:
        return cls(
            patient_id=patient_id,
            one_liner=content.one_liner,
            sections=content.sections,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            faithfulness=faithfulness,
        )

    def to_markdown(self) -> str:
        """Render the summary as clinician-readable markdown (fixed order)."""
        lines: list[str] = [f"# {self.one_liner}", ""]
        for section in self.sections:
            lines.append(f"## {section.heading}")
            if section.no_data or not section.bullets:
                lines.append("_No data recorded._")
            else:
                for b in section.bullets:
                    lines.append(f"- {b.text}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"


Summary.model_rebuild()
