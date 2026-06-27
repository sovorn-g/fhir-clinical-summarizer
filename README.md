# FHIR Clinical Summarizer

Turn a synthetic FHIR R4 patient bundle into a concise, **faithful** clinician-ready summary
a clinician can read in ~10 seconds.

This is the foundational project of the clinical-AI portfolio: its Phase 0 builds the reusable
`clinical_core/` kit (FHIR normalization, an LLM wrapper, and a faithfulness evaluator) that the
later B1 / B3 projects reuse.

> **Status:** Phase 0–4 complete. See [CONTRACTS.md](CONTRACTS.md) for the pinned data models and
> [execute-plan.md](execute-plan.md) for the phase breakdown.

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

## What it does

1. **Ingest** a Synthea FHIR R4 bundle and normalize it into a `PatientRecord` whose every
   clinical fact carries a `SourceRef` (provenance back to the source resource).
2. **Summarize** it into 5 fixed sections — Problems · Medications · Recent Encounters ·
   Key Results · Allergies — using only facts present in the data (never inferred negatives).
3. **Verify** every summary bullet traces to a source resource via a rules-then-LLM-judge
   faithfulness check (target ≥95% of claims traced to source); summaries that fail are
   regenerated once, and otherwise surfaced as failing rather than silently shipped.
4. **Demo** it from the CLI and a Streamlit UI.

## Architecture

```mermaid
flowchart LR
  B[Synthea FHIR R4 bundle\n.json file] --> L[clinical_core.fhir\nload_bundle]
  L --> PR[PatientRecord\n+ SourceRef per fact]
  PR --> R[summarizer.render\nprovenance-tagged context]
  R --> LLM[LLMClient (LiteLLM)\nstructured output]
  LLM --> S[Summary — 5 fixed sections\nbullets carry source_refs]
  S --> F[clinical_core.eval\nfaithfulness: rules → judge]
  F -->|score < 0.95| REGEN[regenerate once\nwith unsupported bullets fed back]
  REGEN --> LLM
  F -->|report| UI[CLI / Streamlit UI]
```

Key design idea: **provenance flows all the way through**. Every normalized clinical fact carries a
`SourceRef`, and the summarizer is told to copy those refs onto each bullet it writes. The
faithfulness checker then validates each bullet against *only* the referenced resources — the judge
sees nothing else, so it can't agree via outside knowledge. That is what makes the summary trustworthy
rather than just fluent.

## Data

Synthetic data only — **no real PHI**. Bundles come from Synthea R4 samples
([smart-on-fhir/generated-sample-data](https://github.com/smart-on-fhir/generated-sample-data),
CC0). 25 patients live in `data/synthea/` (gitignored); three curated, committed
`fixtures/` patients (`alpha` rich, `beta` sparse + missing dates, `gamma` no-known-allergies)
anchor the tests so nothing depends on regenerating Synthea. See [CONTRACTS §2](CONTRACTS.md).

## Usage

### CLI — inspect + summarize

```bash
# normalized record overview + rendered LLM context (no API key needed)
uv run python -m summarizer.cli fixtures/alpha.json --render

# full summary pipeline (needs LLM_MODEL + API key in .env)
uv run python -m summarizer.cli fixtures/alpha.json --summarize
```

### Faithfulness eval report

```bash
uv run python -m clinical_core.eval.faithfulness --fixtures   # 3 committed fixtures, rules-only
uv run python -m clinical_core.eval.faithfulness --n 10        # 10 synthea patients, rules-only
uv run python -m clinical_core.eval.faithfulness --n 10 --live # real LLM + judge (needs API key)
```
Writes `eval_report.md`. Rules-only mode (default) runs with **no API key** using a deterministic
mock summarizer and the rules layer, so the eval is reproducible offline.

### Streamlit demo

```bash
uv run streamlit run src/summarizer/app.py
```

Pick a committed fixture or a generated Synthea bundle (or upload your own FHIR R4 `.json`), tick
**Rules-only** to run offline, and hit **Summarize**. The page shows the markdown summary and a
per-bullet faithfulness table. A demo GIF can be recorded with `ffmpeg`/gifski once you're happy
with the UI.

## Safety / privacy

- **No real PHI.** Only synthetic Synthea data (CC0) is used. The demo never uploads anything to a
  server; processing is local — the only outbound call is to the LLM provider you set in `.env`.
- **No invented negatives.** The renderer — not the model — decides section emptiness; "No known
  allergies" is only ever emitted as a traced bullet when an explicit AllergyIntolerance asserts it
  (see fixtures/gamma). See [CONTRACTS §5](CONTRACTS.md).

## Layout

See [CONTRACTS §1](CONTRACTS.md) for the full layout. TL;DR:

```
src/clinical_core/   # shared kit: fhir/ (models, extract, loader), llm/ (client), config/, eval/
src/summarizer/      # render, prompts, pipeline, cli, app
fixtures/            # alpha (rich), beta (sparse+missing dates), gamma (no-known-allergies)
tests/               # pytest + syrupy snapshots (tests/__snapshots__/)
eval_report.md       # generated by the eval runner (gitignored)
```