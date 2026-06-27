"""CLI: ``python -m summarizer.cli <bundle.json>``.

Phase 0 inspection tool — loads a bundle and prints the normalized ``PatientRecord`` plus the
compact rendered context. (Phase 2 adds: ``--summarize`` to run the full summary pipeline.)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clinical_core.fhir import load_bundle
from summarizer.pipeline import summarize
from summarizer.render import render_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect / summarize a FHIR R4 patient bundle.")
    parser.add_argument("bundle", type=Path, help="path to a Synthea FHIR R4 .json bundle")
    parser.add_argument(
        "--render", action="store_true", help="print the compact rendered LLM context too"
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="run the full summarization pipeline (needs LLM_MODEL + API key in .env)",
    )
    args = parser.parse_args(argv)

    record = load_bundle(args.bundle)

    print("=== PatientRecord (normalized) ===")
    print(f"patient: {record.patient.name} (id={record.patient.id})")
    print(
        f"  gender={record.patient.gender} age={record.patient.age} "
        f"dob={record.patient.birth_date} deceased={record.patient.deceased}"
    )
    print(
        "  counts: "
        f"conditions={len(record.conditions)} active={len(record.active_conditions)} | "
        f"medications={len(record.medications)} current={len(record.current_medications)} | "
        f"observations={len(record.observations)} abnormal={len(record.abnormal_results)} | "
        f"encounters={len(record.encounters)} | allergies={len(record.allergies)}"
    )
    if args.render:
        print()
        print("=== rendered context ===")
        print(render_record(record))
    if args.summarize:
        print()
        print("=== summary ===")
        summary = summarize(record)
        print(summary.to_markdown())
        print(
            f"\n[model={summary.model} in={summary.input_tokens} out={summary.output_tokens} "
            f"cost=${summary.cost_usd:.4f}]"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
