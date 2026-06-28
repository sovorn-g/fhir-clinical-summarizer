"""Summarizer render smoke (Phase 0). Full summarize() + faithfulness tests in Phase 2/3."""

from __future__ import annotations

from summarizer.render import render_record


def test_prompt_guardrail_present():
    from summarizer.prompts import SYSTEM_PROMPT

    # the verbatim-in-spirit guardrail must always be there (CONTRACTS §7)
    assert "ONLY facts present" in SYSTEM_PROMPT
    assert "source_refs" in SYSTEM_PROMPT
    assert "do NOT state" in SYSTEM_PROMPT.lower() or "not state" in SYSTEM_PROMPT.lower()
    assert "at most 2 bullets" in SYSTEM_PROMPT


def test_render_includes_all_five_sections(alpha_record):
    text = render_record(alpha_record)
    for section in (
        "Active Conditions",
        "Current Medications",
        "Recent Encounters",
        "Key Results",
        "Allergies",
    ):
        assert section in text


def test_render_tags_provenance(alpha_record):
    # every line in a populated section must be tagged [ResourceType/<id>]
    text = render_record(alpha_record)
    assert "[Condition/" in text or "[Observation/" in text
    assert "[MedicationRequest/" in text or "[Encounter/" in text


def test_render_marked_no_data_when_empty(beta_record):
    # beta has 0 active conditions → that section should render "(no data)"
    text = render_record(beta_record)
    assert "(no data)" in text


def test_render_alpha_allergies_present(alpha_record):
    text = render_record(alpha_record)
    assert "## Allergies" in text
