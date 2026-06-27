"""Faithfulness evaluation (CONTRACTS §6).

Phase 0 stub: the report/verdict *models* and the threshold are pinned here so downstream
code (``summarizer.pipeline``, tests) can import them; the two-layer evaluator body is
implemented in Phase 3.

Definitions (CONTRACTS §6):
- Claim = one ``Bullet``. The summarizer returns bullets already carrying ``source_refs``.
- Traced = for ≥1 ``source_ref``: the resource exists in the ``PatientRecord`` *and* an
  LLM-as-judge confirms the bullet text is supported by that resource's normalized fields.
- Two layers, cheap-first: rules layer (dangling resource_id → auto-unsupported) then judge.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from clinical_core.config.settings import get_settings
from clinical_core.fhir.models import PatientRecord

log = logging.getLogger(__name__)

THRESHOLD: float = get_settings().faithfulness_threshold

Verdict = Literal["supported", "partial", "unsupported"]


class ClaimVerdict(BaseModel):
    bullet_text: str
    verdict: Verdict
    refs: list  # list[SourceRef]; kept loose to avoid a hard import cycle


class FaithfulnessReport(BaseModel):
    score: float  # supported / total_claims (partial counts as NOT supported — strict)
    total_claims: int
    verdicts: list[ClaimVerdict]
    passed: bool  # score >= THRESHOLD


def evaluate(
    summary,
    record: PatientRecord,
    *,
    judge=None,  # callable(system, user, schema) -> BaseModel; injected in Phase 3
) -> FaithfulnessReport:
    """Faithfulness check. Body implemented in Phase 3.

    Phase 0 contract surface: returns a stub report so callers / tests can wire up without the
    real LLM judge. ``score`` is NOT computed here yet.
    """
    raise NotImplementedError(
        "clinical_core.eval.faithfulness.evaluate is a Phase 0 stub; implemented in Phase 3."
    )
