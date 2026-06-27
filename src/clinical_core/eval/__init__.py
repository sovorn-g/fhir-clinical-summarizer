"""Faithfulness evaluation public surface (CONTRACTS §6).

Names are imported lazily so ``python -m clinical_core.eval.faithfulness`` doesn't trip the
runpy "already in sys.modules" warning that occurs if the package __init__ eagerly imports the
module being run.
"""

from __future__ import annotations


def __getattr__(name: str):
    if name in {"ClaimVerdict", "FaithfulnessReport", "JudgeDecision", "THRESHOLD", "evaluate"}:
        from clinical_core.eval.faithfulness import (
            THRESHOLD,
            ClaimVerdict,
            FaithfulnessReport,
            JudgeDecision,
            evaluate,
        )

        return {
            "ClaimVerdict": ClaimVerdict,
            "FaithfulnessReport": FaithfulnessReport,
            "JudgeDecision": JudgeDecision,
            "THRESHOLD": THRESHOLD,
            "evaluate": evaluate,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ClaimVerdict", "FaithfulnessReport", "JudgeDecision", "THRESHOLD", "evaluate"]
