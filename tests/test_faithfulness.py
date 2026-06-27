"""Faithfulness evaluator (Phase 3): rules layer + judge layer, with injected mocks."""

from __future__ import annotations

from clinical_core.eval.faithfulness import (
    THRESHOLD,
    ClaimVerdict,
    FaithfulnessReport,
    JudgeDecision,
    evaluate,
)
from summarizer.models import Bullet, Section, Summary


def _summary_from(alpha, *, bad_ref: bool = False, no_refs: bool = False) -> Summary:
    cond = alpha.active_conditions[0]
    med = alpha.current_medications[0]
    ref = {
        "resource_type": cond.source.resource_type,
        "resource_id": "does-not-exist" if bad_ref else cond.source.resource_id,
    }
    sections = [
        Section(
            heading="Problems",
            bullets=[
                Bullet(text=f"Active: {cond.code.label()}", source_refs=[ref]),
            ],
        ),
        Section(
            heading="Medications",
            bullets=[
                Bullet(
                    text=f"Current: {med.code.label()}",
                    source_refs=[
                        {
                            "resource_type": med.source.resource_type,
                            "resource_id": med.source.resource_id,
                        }
                    ],
                ),
            ],
        ),
        Section(heading="Recent Encounters", bullets=[]),
        Section(heading="Key Results", bullets=[]),
        Section(heading="Allergies", bullets=[]),
    ]
    if no_refs:
        sections[0].bullets[0] = Bullet(text="Active: something", source_refs=[])
    return Summary(
        patient_id=alpha.patient.id,
        one_liner="x",
        sections=sections,
        model="test/mock",
    )


def test_threshold_is_95():
    assert THRESHOLD == 0.95


def test_report_model_roundtrip():
    v = ClaimVerdict(bullet_text="x", verdict="supported", refs=[])
    r = FaithfulnessReport(score=1.0, total_claims=1, verdicts=[v], passed=True)
    assert r.score == 1.0 and r.passed is True


def test_rules_layer_flags_dangling_refs(alpha_record):
    # all refs dangling → auto-unsupported, no judge needed
    summary = _summary_from(alpha_record, bad_ref=True)
    report = evaluate(summary, alpha_record, judge=None)
    problems = next(v for v in report.verdicts if "Active" in v.bullet_text)
    assert problems.verdict == "unsupported"
    assert "dangling" in (problems.reason or "")
    assert report.score < 1.0
    assert not report.passed


def test_no_source_refs_is_unsupported(alpha_record):
    summary = _summary_from(alpha_record, no_refs=True)
    report = evaluate(summary, alpha_record, judge=None)
    v = report.verdicts[0]
    assert v.verdict == "unsupported"
    assert "no source_refs" in (v.reason or "")


def test_rules_only_supported_when_refs_valid(alpha_record):
    summary = _summary_from(alpha_record)
    report = evaluate(summary, alpha_record, judge=None)
    # med bullet has valid ref → rules-only fallback returns supported
    med = next(v for v in report.verdicts if "Current" in v.bullet_text)
    assert med.verdict == "supported"


def test_judge_layer_overrides_to_unsupported(alpha_record):
    """Even with valid refs, the judge can return unsupported (e.g. an invented detail)."""
    summary = _summary_from(alpha_record)

    class FakeJudge:
        def __call__(self, system, user, schema):
            # pretend the Problems bullet invents a detail
            return JudgeDecision(verdict="unsupported", reason="invented status")

    report = evaluate(summary, alpha_record, judge=FakeJudge())
    problems = next(v for v in report.verdicts if "Active" in v.bullet_text)
    assert problems.verdict == "unsupported"
    assert not report.passed


def test_judge_supported_gives_passing_score(alpha_record):
    summary = _summary_from(alpha_record)

    class AlwaysSupported:
        def __call__(self, system, user, schema):
            return JudgeDecision(verdict="supported", reason="ok")

    report = evaluate(summary, alpha_record, judge=AlwaysSupported())
    assert report.score == 1.0
    assert report.passed is True


def test_zero_claims_is_vacuously_faithful(alpha_record):
    sections = [
        Section(heading=h, bullets=[])
        for h in ("Problems", "Medications", "Recent Encounters", "Key Results", "Allergies")
    ]
    s = Summary(patient_id=alpha_record.patient.id, one_liner="x", sections=sections, model="m")
    report = evaluate(s, alpha_record, judge=None)
    assert report.total_claims == 0
    assert report.score == 1.0 and report.passed is True
