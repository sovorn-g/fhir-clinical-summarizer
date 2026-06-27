"""Phase 2: summarization pipeline, tested with an injected mock LLM (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from clinical_core.fhir import load_bundle
from clinical_core.llm.client import LLMClient
from summarizer.models import SECTION_ORDER, Summary
from summarizer.pipeline import summarize

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


# A realistic SummaryContent payload for alpha, exercising all five sections, including one
# empty section (Problems is non-empty in alpha; we deliberately make Key Results empty to test
# the no_data normalizer) and provenance refs taken from the real alpha record.
def _alpha_payload(record) -> dict:
    cond = record.active_conditions[0]
    med = record.current_medications[0]
    enc = record.recent_encounters[0]
    alg = record.allergies[0]

    def sr(x):
        return {"resource_type": x.source.resource_type, "resource_id": x.source.resource_id}

    sections = []
    sections.append(
        {
            "heading": "Problems",
            "bullets": [{"text": f"Active: {cond.code.label()}", "source_refs": [sr(cond)]}],
        }
    )
    sections.append(
        {
            "heading": "Medications",
            "bullets": [{"text": f"Current: {med.code.label()}", "source_refs": [sr(med)]}],
        }
    )
    sections.append(
        {
            "heading": "Recent Encounters",
            "bullets": [
                {
                    "text": f"{enc.type.label() if enc.type else 'visit'} on {enc.period_start}",
                    "source_refs": [sr(enc)],
                }
            ],
        }
    )
    sections.append({"heading": "Key Results", "bullets": []})  # empty → no_data
    sections.append(
        {
            "heading": "Allergies",
            "bullets": [{"text": f"Allergy: {alg.substance.label()}", "source_refs": [sr(alg)]}],
        }
    )

    return {
        "one_liner": "33yo M with active conditions and current medications.",
        "sections": sections,
    }


def make_mock_client(payload: dict, *, model: str = "test/mock") -> LLMClient:
    """An LLMClient whose completion returns ``payload`` as JSON, with fake usage."""
    response = {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 80},
    }

    def fake_completion(**kwargs):  # noqa: ARG001
        return response

    return LLMClient(model=model, raw_completion=fake_completion)


def test_summarize_returns_typed_summary(alpha_record):
    payload = _alpha_payload(alpha_record)
    client = make_mock_client(payload)
    summary = summarize(alpha_record, client=client)
    assert isinstance(summary, Summary)
    assert summary.patient_id == alpha_record.patient.id
    assert summary.model == "test/mock"
    assert summary.input_tokens == 120 and summary.output_tokens == 80
    assert summary.one_liner
    assert [s.heading for s in summary.sections] == SECTION_ORDER


def test_empty_section_becomes_no_data(alpha_record):
    payload = _alpha_payload(alpha_record)
    client = make_mock_client(payload)
    summary = summarize(alpha_record, client=client)
    key = next(s for s in summary.sections if s.heading == "Key Results")
    assert key.no_data is True
    assert key.bullets == []
    md = summary.to_markdown()
    assert "_No data recorded._" in md


def test_markdown_has_all_sections_in_order(alpha_record):
    payload = _alpha_payload(alpha_record)
    summary = summarize(alpha_record, client=make_mock_client(payload))
    md = summary.to_markdown()
    # section order in markdown
    idx = {s.heading: md.index(f"## {s.heading}") for s in summary.sections}
    for a, b in zip(SECTION_ORDER, SECTION_ORDER[1:], strict=False):
        assert idx[a] < idx[b]
    assert md.startswith("# ")


def test_summary_rejects_wrong_section_order(alpha_record):
    bad = _alpha_payload(alpha_record)
    bad["sections"] = sorted(bad["sections"], key=lambda s: s["heading"])  # alphabetical
    client = make_mock_client(bad)
    try:
        summarize(alpha_record, client=client)
    except Exception as exc:  # noqa: BLE001 — model_validate failure bubbles as LLMOutputError
        assert (
            "sections" in str(exc).lower()
            or "literal" in str(exc).lower()
            or "order" in str(exc).lower()
        )
    else:
        raise AssertionError("expected validation failure for wrong section order")


def test_bullet_refs_match_real_resources(alpha_record):
    """Every returned source_ref must point to a resource actually present in the record."""
    payload = _alpha_payload(alpha_record)
    summary = summarize(alpha_record, client=make_mock_client(payload))
    valid = {(c.source.resource_type, c.source.resource_id) for c in alpha_record.conditions}
    valid |= {(m.source.resource_type, m.source.resource_id) for m in alpha_record.medications}
    valid |= {(o.source.resource_type, o.source.resource_id) for o in alpha_record.observations}
    valid |= {(e.source.resource_type, e.source.resource_id) for e in alpha_record.encounters}
    valid |= {(a.source.resource_type, a.source.resource_id) for a in alpha_record.allergies}
    for section in summary.sections:
        for bullet in section.bullets:
            assert bullet.source_refs, f"bullet lacks source_refs: {bullet.text}"
            for ref in bullet.source_refs:
                assert (ref.resource_type, ref.resource_id) in valid, (
                    f"dangling ref {ref.resource_type}/{ref.resource_id}"
                )


def test_summarize_uses_real_fixture_files():
    # ensure the pipeline still works when loading from disk (not just the fixture object)
    rec = load_bundle(FIXTURES / "alpha.json")
    payload = _alpha_payload(rec)
    summary = summarize(rec, client=make_mock_client(payload))
    assert summary.patient_id == rec.patient.id
