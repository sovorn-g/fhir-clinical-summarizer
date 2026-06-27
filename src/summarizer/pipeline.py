"""``summarize(record) -> Summary`` (CONTRACTS §5/§7; Phase 2).

Pipeline: render the ``PatientRecord`` → compact provenance-tagged context → ask the LLM for a
``SummaryContent`` (structured output) → wrap with model/usage meta. The renderer — not the model —
decides section emptiness; the model is told to return empty bullet lists for empty sections and we
defensively normalize an empty section to ``no_data``.

Phase 3 adds the faithfulness guardrail with regenerate-on-failure around this call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from clinical_core.fhir.models import PatientRecord
from clinical_core.llm.client import LLMClient
from summarizer.models import SECTION_ORDER, Summary, SummaryContent
from summarizer.prompts import SYSTEM_PROMPT
from summarizer.render import render_record

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


def summarize(record: PatientRecord, *, client: LLMClient | None = None) -> Summary:
    """Produce a clinician-ready ``Summary`` for one patient record.

    Pass a configured ``LLMClient`` (overrides default model). In tests, inject a client whose
    ``raw_completion`` returns a valid ``SummaryContent`` JSON payload (no network needed) — see
    tests/test_pipeline.py.
    """
    client = client or LLMClient()
    content, usage = _call_llm(record, client)
    _normalize_no_data(content, record)
    return Summary.from_content(
        content,
        patient_id=record.patient.id,
        model=client.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
    )


def _call_llm(record: PatientRecord, client: LLMClient):
    user = render_record(record)
    result = client.complete_with_usage(SYSTEM_PROMPT, user, SummaryContent)
    return result.parsed, result.usage


def _normalize_no_data(content: SummaryContent, record: PatientRecord) -> None:
    """Defensive: any section with zero bullets becomes ``no_data=True``.

    The renderer is authoritative for emptiness, but we never fully trust the model: an empty
    bullet list must never render as a clinical assertion.
    """
    for section in content.sections:
        if not section.bullets:
            section.no_data = True
    # ensure all five headings present in order even if the model dropped one
    have = {s.heading: s for s in content.sections}
    if set(have) != set(
        SECTION_ORDER
    ):  # SummaryContent validator already enforces, but keep robust
        return
    content.sections = [have[h] for h in SECTION_ORDER]
