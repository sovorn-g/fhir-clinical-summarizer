"""``summarize(record) -> Summary`` (CONTRACTS §5/§6/§7).

Pipeline: render the ``PatientRecord`` → compact provenance-tagged context → ask the LLM for a
``SummaryContent`` (structured output) → wrap with model/usage meta → run the faithfulness
guardrail → regenerate ONCE if below threshold → attach the report and return.

The renderer — not the model — decides section emptiness; we defensively normalize an empty section
to ``no_data`` (CONTRACTS §5 missing-data trap).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from clinical_core.config.settings import get_settings
from clinical_core.eval.faithfulness import evaluate
from clinical_core.fhir.models import PatientRecord
from clinical_core.llm.client import LLMClient
from summarizer.models import SECTION_ORDER, Summary, SummaryContent
from summarizer.prompts import SYSTEM_PROMPT
from summarizer.render import render_record

log = logging.getLogger(__name__)

THRESHOLD = get_settings().faithfulness_threshold


def summarize(
    record: PatientRecord,
    *,
    client: LLMClient | None = None,
    judge: Callable | None = None,
) -> Summary:
    """Produce a clinician-ready ``Summary`` for one patient record, with a faithfulness guardrail.

    By default, the faithfulness layer is rules-only: every bullet must carry source refs, and
    those refs must exist in the normalized FHIR record. Tests or advanced callers can pass a
    ``judge`` callable to add semantic LLM-as-judge verification.

    When the first summary scores below threshold, the pipeline regenerates ONCE with the
    unsupported bullets fed back; if it still fails, the summary is returned with
    ``faithfulness.passed = False`` surfaced (never silently shipped).
    """
    client = client or LLMClient()
    return _summarize_with_guardrail(record, client, judge=judge)


def _summarize_with_guardrail(
    record: PatientRecord, client: LLMClient, *, judge: Callable | None
) -> Summary:
    content, usage = _call_llm(record, client)
    _normalize_no_data(content, record)
    summary = _summary_from_content(content, record, client.model, usage)

    report = evaluate(summary, record, judge=judge)
    if not report.passed:
        log.warning("faithfulness %.2f < %.2f on first pass; regenerating", report.score, THRESHOLD)
        content2, usage2 = _call_llm(record, client, unsupported=report.verdicts)
        _normalize_no_data(content2, record)
        summary = Summary.from_content(
            content2,
            patient_id=record.patient.id,
            model=client.model,
            input_tokens=usage.input_tokens + usage2.input_tokens,
            output_tokens=usage.output_tokens + usage2.output_tokens,
            cost_usd=usage.cost_usd + usage2.cost_usd,
        )
        report = evaluate(summary, record, judge=judge)
    summary.faithfulness = report
    return summary


def _summary_from_content(content, record, model, usage) -> Summary:
    return Summary.from_content(
        content,
        patient_id=record.patient.id,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
    )


def _call_llm(record: PatientRecord, client: LLMClient, *, unsupported: list | None = None):
    user = render_record(record)
    system = SYSTEM_PROMPT
    if unsupported:
        bad = "\n".join(
            f"- {v.bullet_text}  [verdict: {v.verdict}; reason: {v.reason or 'unsupported'}]"
            for v in unsupported
            if v.verdict != "supported"
        )
        system = (
            system
            + "\n\nIMPORTANT — these claims from your prior attempt were UNSUPPORTED and must be "
            "removed or corrected to match the source data exactly:\n" + bad
        )
    result = client.complete_with_usage(system, user, SummaryContent)
    return result.parsed, result.usage


def _normalize_no_data(content: SummaryContent, record: PatientRecord) -> None:
    """Defensive: any section with zero bullets becomes ``no_data=True``.

    The renderer is authoritative for emptiness, but we never fully trust the model: an empty
    bullet list must never render as a clinical assertion.
    """
    for section in content.sections:
        if not section.bullets:
            section.no_data = True
    have = {s.heading: s for s in content.sections}
    if set(have) != set(SECTION_ORDER):  # validator already enforces, but keep robust
        return
    content.sections = [have[h] for h in SECTION_ORDER]
