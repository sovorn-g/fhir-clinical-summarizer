"""Faithfulness evaluation (CONTRACTS §6).

Two layers, cheap-first:
1. **Rules layer:** for each bullet, check every ``source_ref``'s ``resource_id`` exists in the
   ``PatientRecord``. A bullet whose refs are *all* dangling is auto-``unsupported`` (no LLM call).
2. **Judge layer:** for surviving bullets (≥1 extant ref), call the LLM-as-judge with ONLY the
   bullet text + the JSON of its referenced normalized resources, returning
   ``supported | unsupported | partial`` via structured output. The judge sees nothing else —
   it can't "agree" using outside knowledge.

Metric: ``score = supported / total_claims`` (partial counts as NOT supported — strict).
``passed = score >= THRESHOLD`` (``THRESHOLD = 0.95``). The pipeline (Phase 3) retries once on
failure, feeding the unsupported bullets back.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from clinical_core.config.settings import get_settings
from clinical_core.fhir.models import (
    Allergy,
    Condition,
    Encounter,
    Medication,
    Observation,
    PatientRecord,
    SourceRef,
)

log = logging.getLogger(__name__)

THRESHOLD: float = get_settings().faithfulness_threshold

Verdict = Literal["supported", "partial", "unsupported"]


# --- models -------------------------------------------------------------------
class ClaimVerdict(BaseModel):
    bullet_text: str
    verdict: Verdict
    refs: list[SourceRef] = Field(default_factory=list)
    reason: str | None = None  # short reason from rules or judge


class FaithfulnessReport(BaseModel):
    score: float  # supported / total_claims (partial NOT supported — strict)
    total_claims: int
    verdicts: list[ClaimVerdict]
    passed: bool  # score >= THRESHOLD


class JudgeDecision(BaseModel):
    """Structured output schema the LLM-as-judge must return."""

    verdict: Verdict
    reason: str = ""


# --- judge prompt -------------------------------------------------------------
_JUDGE_SYSTEM = """\
You are a strict clinical faithfulness judge. You are given ONE bullet (a short clinical claim)
and the JSON of the FHIR resource(s) it is supposed to be derived from.

Decide if the bullet is SUPPORTED by those resources:
- "supported" — every assertion in the bullet is directly present in or trivially entailed by the
  given resource fields.
- "partial" — the bullet is partly supported but adds a detail not in the resources, or overstates.
- "unsupported" — the bullet makes a claim the resources do not support (numbers, statuses, dates,
  named conditions, or any clinical inference not in the data).

Use ONLY the provided resource JSON. Do NOT use outside medical knowledge to "agree" with the bullet.
Return JSON: {"verdict": "...", "reason": "..."}.
"""


# --- public API ---------------------------------------------------------------
def evaluate(
    summary,
    record: PatientRecord,
    *,
    judge=None,  # callable(system, user, schema) -> JudgeDecision; injected in tests
) -> FaithfulnessReport:
    """Return a ``FaithfulnessReport`` for ``summary`` against ``record``.

    ``judge`` is any callable ``(system, user, schema) -> BaseModel`` matching the LLMClient
    signature; in production pass ``LLMClient(model=<judge_model>).complete_with_usage`` or wrap
    ``LLMClient.complete``. If ``judge`` is None, only the rules layer runs (dangling refs →
    unsupported; extant refs → treated as ``supported`` since no judge is available) — useful for
    tests and offline checks.
    """
    index = _resource_index(record)
    verdicts: list[ClaimVerdict] = []

    for section in summary.sections:
        for bullet in section.bullets:
            verdicts.append(_judge_bullet(bullet, index, judge))

    total = len(verdicts)
    supported = sum(1 for v in verdicts if v.verdict == "supported")
    score = supported / total if total else 1.0  # no claims → vacuously faithful
    return FaithfulnessReport(
        score=score,
        total_claims=total,
        verdicts=verdicts,
        passed=score >= THRESHOLD,
    )


# --- internals ----------------------------------------------------------------
def _resource_index(record: PatientRecord) -> dict[str, object]:
    """Map resource_id → normalized model, across all clinical resource types."""
    index: dict[str, object] = {}
    for coll in (
        record.conditions,
        record.medications,
        record.observations,
        record.encounters,
        record.allergies,
    ):
        for item in coll:
            index[item.source.resource_id] = item
    return index


def _judge_bullet(bullet, index: dict[str, object], judge) -> ClaimVerdict:
    refs = list(bullet.source_refs)
    if not refs:
        return ClaimVerdict(
            bullet_text=bullet.text,
            verdict="unsupported",
            refs=[],
            reason="no source_refs on bullet",
        )

    extant = [(ref, index.get(ref.resource_id)) for ref in refs if ref.resource_id in index]
    dangling = [ref for ref in refs if ref.resource_id not in index]

    # all dangling → auto-unsupported (rules layer; no LLM call)
    if not extant:
        return ClaimVerdict(
            bullet_text=bullet.text,
            verdict="unsupported",
            refs=refs,
            reason=f"all {len(refs)} source ref(s) dangling",
        )

    # judge layer (or rules-only fallback)
    if judge is None:
        # rules-only fallback: extant refs → supported (with a note about hanging ones if any)
        verdict: Verdict = "supported" if not dangling else "partial"
        reason = "rules-only (no judge)" + (
            f"; {len(dangling)} dangling ref(s) ignored" if dangling else ""
        )
        return ClaimVerdict(bullet_text=bullet.text, verdict=verdict, refs=refs, reason=reason)

    resource_json = json.dumps(
        [_resource_payload(obj) for _ref, obj in extant],
        default=str,
        indent=2,
    )
    user = f"Bullet:\n{bullet.text}\n\nResources:\n{resource_json}"
    try:
        decision = judge(_JUDGE_SYSTEM, user, JudgeDecision)
        decision = decision.parsed if hasattr(decision, "parsed") else decision
    except Exception as exc:  # noqa: BLE001 — judge failure must not crash the run
        log.warning("judge call failed for bullet %r: %s", bullet.text, exc)
        return ClaimVerdict(
            bullet_text=bullet.text,
            verdict="unsupported",
            refs=refs,
            reason=f"judge error: {exc}",
        )
    return ClaimVerdict(
        bullet_text=bullet.text,
        verdict=decision.verdict,
        refs=refs,
        reason=decision.reason or None,
    )


def _resource_payload(obj) -> dict:
    """Small, judge-facing dict of one normalized resource (no provenance noise)."""
    if isinstance(obj, Condition):
        return _coding(obj.code) | {
            "clinical_status": obj.clinical_status,
            "verification_status": obj.verification_status,
            "onset_date": obj.onset_date,
            "recorded_date": obj.recorded_date,
        }
    if isinstance(obj, Medication):
        return _coding(obj.code) | {
            "status": obj.status,
            "dosage_text": obj.dosage_text,
            "authored_on": obj.authored_on,
        }
    if isinstance(obj, Observation):
        return _coding(obj.code) | {
            "value": obj.value,
            "unit": obj.unit,
            "interpretation": obj.interpretation,
            "effective_date": obj.effective_date,
            "reference_range": obj.reference_range,
        }
    if isinstance(obj, Encounter):
        out: dict = {
            "encounter_class": obj.encounter_class,
            "status": obj.status,
            "period_start": obj.period_start,
            "period_end": obj.period_end,
        }
        if obj.type:
            out |= _coding(obj.type)
        if obj.reason:
            out["reason"] = _coding(obj.reason)
        return out
    if isinstance(obj, Allergy):
        return _coding(obj.substance) | {
            "clinical_status": obj.clinical_status,
            "criticality": obj.criticality,
            "reaction": obj.reaction,
        }
    return {"unknown": str(type(obj))}


def _coding(c) -> dict:
    return {"display": c.display, "text": c.text, "code": c.code, "system": c.system}


# --- eval runner (CONTRACTS §9) ----------------------------------------------
def _build_mock_summary(record):
    """Deterministic mock summary: one traced bullet per non-empty filtered view + empty sections."""
    from summarizer.models import Bullet, Section, Summary

    def sr(x):
        return [{"resource_type": x.source.resource_type, "resource_id": x.source.resource_id}]

    def section(heading, items, fmt):
        if items:
            it = items[0]
            return Section(heading=heading, bullets=[Bullet(text=fmt(it), source_refs=sr(it))])
        return Section(heading=heading, bullets=[], no_data=True)

    sections = [
        section("Problems", record.active_conditions, lambda c: f"Active: {c.code.label()}"),
        section("Medications", record.current_medications, lambda m: f"Current: {m.code.label()}"),
        section(
            "Recent Encounters",
            record.recent_encounters,
            lambda e: f"{e.type.label() if e.type else 'visit'}",
        ),
        section(
            "Key Results", record.abnormal_results, lambda o: f"{o.code.label()} {o.interpretation}"
        ),
        section("Allergies", record.allergies, lambda a: f"Allergy: {a.substance.label()}"),
    ]
    return Summary(
        patient_id=record.patient.id,
        one_liner="(mock eval patient)",
        sections=sections,
        model="mock",
    )


def _render_report(rows, *, live):
    lines = [
        "# Faithfulness Eval Report",
        "",
        f"- Mode: {'live (LLM + judge)' if live else 'rules-only (mock summarizer)'}",
        f"- Patients: {len(rows)}",
        "- Threshold: 0.95",
        "",
        "| Patient | Claims | Supported | Score | Passed |",
        "|---|---:|---:|---:|:---:|",
    ]
    for name, _summary, report in rows:
        supported = sum(1 for v in report.verdicts if v.verdict == "supported")
        lines.append(
            f"| {name} | {report.total_claims} | {supported} | {report.score:.2f} | "
            f"{'✅' if report.passed else '❌'} |"
        )
    passing = sum(1 for _n, _s, r in rows if r.passed)
    lines += ["", f"**Overall pass: {passing}/{len(rows)}**", ""]
    return "\n".join(lines) + "\n"


def run_eval(*, n: int, fixtures: bool, out, live: bool) -> int:
    from pathlib import Path

    from clinical_core.fhir import load_bundle

    repo = Path(__file__).resolve().parents[3]
    if fixtures:
        bundles = sorted((repo / "fixtures").glob("*.json"))
    else:
        all_b = sorted((repo / "data" / "synthea").glob("*.json"))
        bundles = all_b[:n] if n else all_b
    if not bundles:
        print("no bundles found", file=__import__("sys").stderr)
        return 2
    print(f"evaluating {len(bundles)} patients — {'live' if live else 'rules-only'}")
    rows = []
    for b in bundles:
        rec = load_bundle(b)
        if live:
            from summarizer.pipeline import summarize as summarize_live

            summary = summarize_live(rec)
            report = summary.faithfulness or evaluate(summary, rec, judge=None)
        else:
            summary = _build_mock_summary(rec)
            report = evaluate(summary, rec, judge=None)
        rows.append((b.stem, summary, report))
    out.write_text(_render_report(rows, live=live), encoding="utf-8")
    passing = sum(1 for _n, _s, r in rows if r.passed)
    print(f"wrote {out}  pass: {passing}/{len(rows)}")
    return 0 if passing == len(rows) else 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    import logging
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    p = argparse.ArgumentParser(prog="clinical_core.eval.faithfulness")
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--fixtures", action="store_true")
    p.add_argument("--out", type=Path, default=repo / "eval_report.md")
    p.add_argument("--live", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    return run_eval(n=args.n, fixtures=args.fixtures, out=args.out, live=args.live)


if __name__ == "__main__":
    import sys

    sys.exit(main())
