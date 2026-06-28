"""Generate a committed-ready sample summary from a synthetic FHIR fixture.

Usage:
    uv run python scripts/sample.py
    uv run python scripts/sample.py --bundle fixtures/beta.json --out examples/beta-summary.md

Requires live LLM configuration in .env:
    LLM_MODEL=provider/model
    API_KEY=...
"""

from __future__ import annotations

import argparse
from pathlib import Path

from clinical_core.fhir import load_bundle
from clinical_core.llm.client import LLMClient, LLMOutputError
from summarizer.pipeline import summarize


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a sample clinical summary markdown file."
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("fixtures/alpha.json"),
        help="FHIR R4 bundle to summarize",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("examples/alpha-summary.md"),
        help="where to write the generated markdown summary",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="maximum output tokens for the live model",
    )
    args = parser.parse_args()

    record = load_bundle(args.bundle)
    try:
        summary = summarize(record, client=LLMClient(max_tokens=args.max_tokens))
    except LLMOutputError as exc:
        print(f"Model returned invalid JSON: {exc}")
        print("Retry with a larger output budget, for example: --max-tokens 6000")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(summary.to_markdown(), encoding="utf-8")

    print(f"Wrote {args.out}")
    print(f"Model: {summary.model}")
    print(f"Tokens in/out: {summary.input_tokens}/{summary.output_tokens}")
    print(f"Cost: ${summary.cost_usd:.4f}")
    if summary.faithfulness is not None:
        report = summary.faithfulness
        print(f"Faithfulness: {report.score:.0%} ({'passed' if report.passed else 'failed'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
