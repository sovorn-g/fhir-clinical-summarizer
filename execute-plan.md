# FHIR Clinical Summarizer — Execution Plan

> **Tier:** 🟢 Small · **Est. effort:** 1–3 days · **Status:** 🔴 Not started
> **Reuses:** — (this project builds the shared foundation) · **Feeds into:** B1, B3
>
> **Before coding, read [CONTRACTS.md](CONTRACTS.md)** — it pins the data models (`PatientRecord`,
> `Summary`, provenance `SourceRef`), repo layout, Synthea seed/version, the LLM wrapper (model id,
> structured output, caching), the faithfulness method, and the test fixtures. This plan is the *what/why*;
> CONTRACTS is the *how*. A coding agent should not invent those interfaces.

---

## 1. Overview
Ingest a patient's FHIR record (synthetic, from Synthea), select the clinically relevant resources,
and produce a concise plain-English patient summary an clinician can read in ~10 seconds. This is the
foundational project: its Phase 0 builds the **shared core kit** (`clinical_core/`) reused everywhere.

## 2. Why This Project (Market Context)
Summarisation of fragmented EHR data is the entry-level workhorse of clinical AI — every downstream
tool (scribe, CDS, chart search) depends on turning structured FHIR into something an LLM and a human
can reason over. Proves the core competency: *"I can work with real health-data structures."*

## 3. Success Criteria
- [ ] Given any Synthea patient bundle, output a structured markdown summary (Problems, Meds, Recent
      Encounters, Key Results, Allergies).
- [ ] Summary contains **no facts absent from the source** (factuality check passes).
- [ ] Runs from CLI and a minimal web UI.
- [ ] < 15s end-to-end for a typical patient.

## 4. Tech Stack
Python 3.11+, `fhir.resources` (Pydantic FHIR models), Anthropic SDK (Claude), Pydantic v2,
Streamlit (demo UI), pytest, ruff. Package mgmt: `uv`.

## 5. Data Source
[Synthea](https://github.com/synthetichealth/synthea) — generate ~25 synthetic patients as FHIR R4
bundles. **No real PHI.**

## 6. Prerequisites & Dependencies
- Anthropic API key in `.env`.
- Java (to run Synthea) OR use Synthea's pre-generated sample FHIR bundles.

## 7. Execution Phases

### Phase 0 — Shared Foundation + Repo Setup
**Objectives:** Stand up the reusable `clinical_core/` kit and project scaffolding.
**Key tasks:**
- [ ] Init repo, `uv` env, ruff + pytest + pre-commit, `.env.example`.
- [ ] Install/run Synthea; generate 25 patient FHIR bundles into `data/synthea/`.
- [ ] Build `clinical_core/llm/` — provider-agnostic wrapper (Claude default), retries, structured
      output via Pydantic, token/cost logging.
- [ ] Build `clinical_core/fhir/` — load bundle → normalized intermediate models
      (Patient, Condition, MedicationRequest, Observation, Encounter, AllergyIntolerance).
- [ ] Build `clinical_core/eval/` — stub factuality checker.
**Deliverable:** Importable `clinical_core` package + sample data.
**Acceptance:** `pytest` green; can load a bundle and print normalized models.

### Phase 1 — FHIR Ingestion & Normalization
**Objectives:** Turn raw bundles into a clean, summary-ready patient object.
**Key tasks:**
- [ ] Parse bundle → `PatientRecord` aggregate (demographics + grouped clinical resources).
- [ ] Sort/filter: active conditions, current meds, last N encounters, abnormal results.
- [ ] Handle missing/partial data gracefully.
**Deliverable:** `PatientRecord` model + loader.
**Acceptance:** Snapshot test on 3 fixture patients produces stable normalized output.

### Phase 2 — Summarization Pipeline
**Objectives:** Generate the summary.
**Key tasks:**
- [ ] Design prompt with explicit sections + "only use provided facts" instruction.
- [ ] Render `PatientRecord` → compact structured context (token-budget aware).
- [ ] Call LLM with structured output; produce markdown summary.
**Deliverable:** `summarize(record) -> Summary`.
**Acceptance:** Readable, correctly sectioned summaries for 5 sample patients.

### Phase 3 — Evaluation & Guardrails
**Objectives:** Prove the summary is faithful.
**Key tasks:**
- [ ] Factuality check: extract claims, verify each against source resources (LLM-as-judge + rules).
- [ ] Flag/regenerate on hallucination; log a faithfulness score.
- [ ] Small eval set (10 patients) with pass/fail report.
**Deliverable:** `eval/faithfulness.py` + report.
**Acceptance:** ≥ 95% of sampled claims trace to source.

### Phase 4 — Demo UI + Polish
**Objectives:** Make it presentable.
**Key tasks:**
- [ ] Streamlit: pick/upload bundle → show summary + faithfulness score.
- [ ] README (problem, architecture diagram, demo GIF, clinical rationale), privacy note.
**Deliverable:** Running demo + portfolio README.
**Acceptance:** Fresh clone runs in < 5 min via documented steps.

## 8. Portfolio Deliverables
README + architecture diagram + demo GIF; LinkedIn angle: *"Turning fragmented FHIR records into a
10-second clinician-ready summary — faithfully."*

## 9. Risks & Notes
- LLM hallucination is the core risk → Phase 3 is non-negotiable.
- Keep `clinical_core` clean from day one; B1/B3 depend on it.

## 10. Definition of Done
All success criteria met, eval report committed, demo recorded, README published, `clinical_core`
extracted as a reusable local package.
