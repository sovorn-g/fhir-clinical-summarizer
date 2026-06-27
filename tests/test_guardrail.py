"""Phase 3: pipeline regenerate-on-failure guardrail, with mock LLM + mock judge."""

from __future__ import annotations

import json

from _helpers import alpha_payload
from clinical_core.eval.faithfulness import JudgeDecision
from clinical_core.llm.client import LLMClient
from summarizer.pipeline import summarize


def _client(payload, *, model="test/mock") -> LLMClient:
    resp = {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 30},
    }
    return LLMClient(model=model, raw_completion=lambda **k: resp)


def make_judge(verdicts_for):
    """Return a judge that returns 'unsupported' for bullets containing any substring in verdicts_for."""

    class _J:
        def __call__(self, system, user, schema):
            for needle, v in verdicts_for.items():
                if needle in user:
                    return JudgeDecision(verdict=v, reason="mock")
            return JudgeDecision(verdict="supported", reason="ok")

    return _J()


def test_guardrail_passes_first_pass(alpha_record):
    payload = alpha_payload(alpha_record)
    summary = summarize(alpha_record, client=_client(payload), judge=make_judge({}))
    assert summary.faithfulness is not None
    assert summary.faithfulness.passed is True
    assert summary.faithfulness.score == 1.0


def test_guardrail_regenerates_on_failure(alpha_record):
    # First pass: judge rejects the Problems bullet; second pass uses same payload (still rejected)
    # → summary returned with passed=False (regenerate-once semantics, surfaced, not hidden).
    payload = alpha_payload(alpha_record)
    judge = make_judge({"Active:": "unsupported"})  # Problems bullet says "Active: ..."
    summary = summarize(alpha_record, client=_client(payload), judge=judge)
    assert summary.faithfulness is not None
    assert summary.faithfulness.passed is False
    v = next(x for x in summary.faithfulness.verdicts if "Active" in x.bullet_text)
    assert v.verdict == "unsupported"


def test_guardrail_recovery_second_pass(alpha_record):
    """If the second attempt's bullets are all supported, we pass even after a failed first pass."""
    payload2 = alpha_payload(alpha_record)
    # Make Problems bullet supported-by-data text the judge accepts
    payload2["sections"][0]["bullets"][0]["text"] = "Current active condition present"
    calls = {"n": 0}

    def completion(**kwargs):  # noqa: ARG001
        calls["n"] += 1
        return {
            "choices": [{"message": {"content": json.dumps(payload2)}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 25},
        }

    client = LLMClient(model="test/mock", raw_completion=completion)

    # First pass: judge rejects the "Current active condition present" bullet too → regenerates
    # to the same payload but now judge accepts (stateful). Verify regenerate happened.
    class Stateful:
        def __init__(self):
            self.first = True

        def __call__(self, system, user, schema):
            if self.first:
                self.first = False
                return JudgeDecision(verdict="unsupported", reason="try again")
            return JudgeDecision(verdict="supported", reason="ok")

    summary = summarize(alpha_record, client=client, judge=Stateful())
    assert calls["n"] == 2, "pipeline should regenerate exactly once"
    assert summary.faithfulness.passed is True
    # token totals should reflect BOTH calls
    assert summary.input_tokens == 80 and summary.output_tokens == 50


def test_guardrail_runs_rules_only_without_judge(alpha_record):
    payload = alpha_payload(alpha_record)
    summary = summarize(alpha_record, client=_client(payload), judge=None)
    # rules-only: valid refs → supported → passes
    assert summary.faithfulness.passed is True
    assert all(v.verdict == "supported" for v in summary.faithfulness.verdicts)
