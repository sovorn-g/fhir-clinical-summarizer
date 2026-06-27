"""Faithfulness evaluator surface (Phase 0 stub). Body tests land in Phase 3."""

from __future__ import annotations

import pytest

from clinical_core.eval.faithfulness import (
    THRESHOLD,
    ClaimVerdict,
    FaithfulnessReport,
    evaluate,
)


def test_threshold_is_95():
    assert THRESHOLD == 0.95


def test_report_model_roundtrip():
    v = ClaimVerdict(bullet_text="x", verdict="supported", refs=[])
    r = FaithfulnessReport(score=1.0, total_claims=1, verdicts=[v], passed=True)
    assert r.score == 1.0 and r.passed is True


def test_evaluate_is_phase0_stub():
    with pytest.raises(NotImplementedError):
        evaluate(summary=None, record=object())
