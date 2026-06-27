# FHIR Clinical Summarizer

Turn a synthetic FHIR R4 patient bundle into a concise, **faithful** clinician-ready summary
a clinician can read in ~10 seconds.

This is the foundational project of the clinical-AI portfolio: its Phase 0 builds the reusable
`clinical_core/` kit (FHIR normalization, an LLM wrapper, and a faithfulness evaluator) that the
later B1 / B3 projects reuse.

> **Status:** Phase 0 (shared foundation) is complete; Phases 1–4 follow the [execution plan](execute-plan.md).  See [CONTRACTS.md](CONTRACTS.md) for the pinned data models.

## Quick start

```bash
# Python 3.11+ and uv (https://docs.astral.sh/uv)
cp .env.example .env            # fill in an API key
uv sync --extra dev             # create venv + install deps (uv.lock is committed)
uv run pytest                   # should be green
uv run python -c "from clinical_core.fhir import load_bundle; print(load_bundle('fixtures/alpha.json').patient)"
```

If you *intentionally* change FHIR extraction, update the syrupy snapshots:

```bash
uv run pytest --snapshot-update   # review the diff in tests/__snapshots__ before committing
```

## What it does (target)

1. **Ingest** a Synthea FHIR R4 bundle and normalize it into a `PatientRecord` whose every
   clinical fact carries a `SourceRef` (provenance back to the source resource).
2. **Summarize** it into 5 fixed sections — Problems · Medications · Recent Encounters ·
   Key Results · Allergies — using only facts present in the data (never inferred negatives).
3. **Verify** every summary bullet traces to a source resource via a rules-then-LLM-judge
   faithfulness check (target ≥95% of claims traced to source).
4. **Demo** it from the CLI and a Streamlit UI.

## Data

Synthetic data only — **no real PHI**. Bundles come from Synthea R4 samples
([smart-on-fhir/generated-sample-data](https://github.com/smart-on-fhir/generated-sample-data),
CC0). 25 patients live in `data/synthea/` (gitignored); three curated, committed
`fixtures/` patients (`alpha` rich, `beta` sparse + missing dates, `gamma` no-known-allergies)
anchor the tests so nothing depends on regenerating Synthea. See [CONTRACTS §2](CONTRACTS.md).

## Layout

See [CONTRACTS §1](CONTRACTS.md) for the full layout. TL;DR:

```
src/clinical_core/   # shared kit: fhir/ (models, extract, loader), llm/ (client), config/, eval/
src/summarizer/      # render, prompts, pipeline, cli, app
fixtures/            # alpha, beta, gamma — committed, curated
tests/               # pytest + syrupy snapshots
```