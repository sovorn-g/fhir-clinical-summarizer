"""``summarize(record) -> Summary`` (Phase 2).

Phase 0 placeholder — the real pipeline (render → LLM structured output →
faithfulness guardrail with regenerate-on-failure) lands in Phase 2/3 per the execution plan.
"""

from __future__ import annotations


def summarize(record, *, client=None):
    """Return a :class:`Summary`. Implemented in Phase 2."""
    raise NotImplementedError(
        "summarizer.pipeline.summarize is a Phase 0 stub; implemented in Phase 2."
    )
