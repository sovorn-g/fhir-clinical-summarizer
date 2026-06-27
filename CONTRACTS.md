# CONTRACTS — FHIR Clinical Summarizer

> Companion to [execute-plan.md](execute-plan.md). The plan says **what** and **why**; this file pins
> the **interfaces, schemas, and methods** a coding agent would otherwise have to invent. Because
> Phase 0 builds the shared `clinical_core/` kit that B1 and B3 depend on, the data contracts here are
> load-bearing for the whole portfolio — change them deliberately, not by accident.
>
> Status of each contract: 🔒 = frozen (downstream depends on it), 🟡 = sensible default, change if needed.

---

## 1. Repo layout & packaging 🔒

`clinical_core/` lives **inside this repo** under a `src/` layout for now. Extraction into a separately
installable package happens later (out of scope for this repo) once the models stabilize — until then,
downstream projects vendor or path-install it. Do **not** spend Phase 0 effort on packaging it standalone.

```
fhir-clinical-summarizer/
├── pyproject.toml              # uv-managed; ruff + pytest + coverage config live here
├── .env.example                # ANTHROPIC_API_KEY, CLINICAL_LLM_MODEL, ...
├── .pre-commit-config.yaml     # ruff (lint+format), end-of-file, trailing-whitespace
├── README.md
├── execute-plan.md
├── CONTRACTS.md                # this file
├── data/
│   └── synthea/                # generated bundles — gitignored except fixtures/
├── fixtures/                   # committed, curated test patients (see §8)
│   ├── alpha.json
│   ├── beta.json
│   └── gamma.json
├── src/
│   ├── clinical_core/
│   │   ├── __init__.py
│   │   ├── config/
│   │   │   └── settings.py     # pydantic-settings; reads .env
│   │   ├── fhir/
│   │   │   ├── models.py       # normalized intermediate models (§3)
│   │   │   ├── extract.py      # raw FHIR resource → normalized model
│   │   │   └── loader.py       # bundle → PatientRecord (§4)
│   │   ├── llm/
│   │   │   ├── client.py       # provider-agnostic wrapper (§7)
│   │   │   └── types.py        # Usage, LLMResult
│   │   └── eval/
│   │       └── faithfulness.py # §6
│   └── summarizer/
│       ├── __init__.py
│       ├── render.py           # PatientRecord → compact LLM context
│       ├── prompts.py          # system prompt + section spec
│       ├── pipeline.py         # summarize(record) -> Summary
│       ├── cli.py              # `python -m summarizer.cli <bundle.json>`
│       └── app.py              # Streamlit demo
└── tests/
    ├── conftest.py             # loads fixtures/ as PatientRecord fixtures
    ├── test_loader.py
    ├── test_summarize.py
    ├── test_faithfulness.py
    └── snapshots/              # syrupy/__snapshots__ for normalized-output tests
```

Import surface: `from clinical_core.fhir import load_bundle, PatientRecord`, `from clinical_core.llm import LLMClient`.

---

## 2. Synthea data generation 🔒

Reproducibility requires a pinned seed. Generate **FHIR R4 transaction bundles**, one file per patient.

| Setting | Value |
|---|---|
| Synthea version | tag `v3.3.0` (or pin whatever the first run uses — record it in README) |
| Population | `-p 25` |
| Seed | `-s 20260627` (clock + population seed; record the exact command) |
| FHIR version | R4 (`exporter.fhir.export = true`, STU3/DSTU2 off) |
| Output | `data/synthea/*.json` |

Command (documented in README): `./run_synthea -p 25 -s 20260627 -a 18-90 Massachusetts`.
**Escape hatch:** if Java/Synthea isn't available, use Synthea's published sample R4 bundles and copy 25
into `data/synthea/`. Either way, the three `fixtures/` patients (§8) are committed so tests never depend
on regenerating data.

---

## 3. Normalized intermediate models 🔒

Pydantic v2 models in `clinical_core/fhir/models.py`. **Every clinical fact carries a `SourceRef`** so the
faithfulness checker (§6) can trace each summary claim back to the FHIR resource it came from. This
provenance is the single most important design decision in the kit — do not drop it to save effort.

```python
class SourceRef(BaseModel):
    resource_type: str          # "Condition", "MedicationRequest", ...
    resource_id: str            # FHIR resource id
    fhir_path: str | None = None  # optional: where in the resource the value came from

class Coding(BaseModel):
    system: str | None          # e.g. "http://snomed.info/sct"
    code: str | None
    display: str | None
    text: str | None            # CodeableConcept.text fallback

class PatientDemographics(BaseModel):
    id: str
    name: str                   # rendered "Given Family"
    gender: str | None
    birth_date: date | None
    age: int | None             # derived at load time, relative to today
    deceased: bool = False

class Condition(BaseModel):
    code: Coding
    clinical_status: str | None     # active | recurrence | relapse | inactive | remission | resolved
    verification_status: str | None # confirmed | provisional | ...
    onset_date: date | None
    recorded_date: date | None
    source: SourceRef

class Medication(BaseModel):           # from MedicationRequest (+ MedicationStatement if present)
    code: Coding
    status: str | None              # active | completed | stopped | ...
    dosage_text: str | None
    authored_on: date | None
    source: SourceRef

class Observation(BaseModel):          # labs + vitals
    code: Coding
    value: float | str | None
    unit: str | None
    interpretation: str | None      # normalized to one of: N, H, L, HH, LL, A (abnormal), or None
    effective_date: date | None
    reference_range: str | None
    source: SourceRef

class Encounter(BaseModel):
    type: Coding | None
    encounter_class: str | None     # AMB, EMER, IMP, ...
    status: str | None
    period_start: date | None
    period_end: date | None
    reason: Coding | None
    source: SourceRef

class Allergy(BaseModel):
    substance: Coding
    clinical_status: str | None
    criticality: str | None         # low | high | unable-to-assess
    reaction: str | None            # first manifestation text, if any
    source: SourceRef
```

**Extraction rules** (`extract.py`):
- Prefer `coding[0].display`; fall back to `CodeableConcept.text`; never invent a display string.
- Dates: accept `dateTime`/`date`/`Period.start`; store as `date`. Unparseable → `None`, never a guess.
- `Observation.interpretation`: map FHIR interpretation codes (`H`,`L`,`HH`,`LL`,`A`,`AA`) to the enum
  above; if absent but a numeric value falls outside `referenceRange`, derive `H`/`L`; else `N`.
- Skip resources that fail validation; log the count. Partial data is expected, not an error.

---

## 4. `PatientRecord` aggregate & filtering 🔒

```python
class PatientRecord(BaseModel):
    patient: PatientDemographics
    conditions: list[Condition]
    medications: list[Medication]
    observations: list[Observation]
    encounters: list[Encounter]
    allergies: list[Allergy]
    source_bundle_path: str

def load_bundle(path: str | Path) -> PatientRecord: ...
```

The summarizer consumes **filtered views**, computed by helper methods/properties with these exact rules
(so snapshot tests are stable):

| View | Rule |
|---|---|
| `active_conditions` | `clinical_status in {active, recurrence, relapse}`, sorted by `onset_date` desc (None last) |
| `current_medications` | `status == active`, sorted by `authored_on` desc |
| `recent_encounters` | all encounters sorted by `period_start` desc, take first **N=5** |
| `abnormal_results` | `interpretation in {H, L, HH, LL, A, AA}`, sorted by `effective_date` desc, take first **N=10** |

`N` values live in `clinical_core/config/settings.py` as defaults so they're tunable without code edits.

---

## 5. `Summary` model & missing-data rules 🔒

```python
class Bullet(BaseModel):
    text: str
    source_refs: list[SourceRef]    # every bullet must trace to ≥1 source (enforced in §6)

class Section(BaseModel):
    heading: str                    # fixed set & order, see below
    bullets: list[Bullet]
    no_data: bool = False           # True when section has no source resources

class Summary(BaseModel):
    patient_id: str
    one_liner: str                  # e.g. "72yo F with T2DM, HTN, and CKD stage 3."
    sections: list[Section]
    model: str
    generated_at: datetime
    input_tokens: int
    output_tokens: int
    cost_usd: float
    faithfulness: FaithfulnessReport | None = None  # §6
```

**Fixed sections, in this order:** `Problems`, `Medications`, `Recent Encounters`, `Key Results`, `Allergies`.

### Missing-data handling — the faithfulness trap 🔒
Distinguish **absence of data** from **asserted absence**. This is a real clinical-safety subtlety, not pedantry:

- A section with no source resources renders `_No data recorded._` and sets `no_data = True`.
- **Never** emit "No known allergies" / "No active problems" as a clinical assertion **unless** there is an
  explicit FHIR resource asserting it (e.g. an `AllergyIntolerance` with code `no-known-allergies` /
  SNOMED `716186003`). Synthea sometimes emits these — when present, render them as a normal traced bullet.
- The prompt (§7) forbids the model from inferring negatives. The renderer, not the model, is responsible
  for the `_No data recorded._` placeholder.

---

## 6. Faithfulness evaluation 🔒

`clinical_core/eval/faithfulness.py`. This is Phase 3 and the whole point of the project — specified
concretely here so it isn't hand-waved.

**Definitions**
- **Claim** = one `Bullet`. The summarizer is required to return bullets already carrying `source_refs`
  (the LLM emits them via structured output, §7), so claim extraction is mostly free.
- **Traced** = a claim is *traced* if, for at least one of its `source_refs`, the referenced resource
  exists in the `PatientRecord` **and** an LLM-as-judge confirms the bullet text is supported by that
  resource's normalized fields. Rules-layer first (does the `resource_id` exist? does the code/value
  appear?), judge only the residual.

**Method** (two layers, cheap-first):
1. **Rules layer:** for each `source_ref`, confirm `resource_id` exists in the record. A bullet whose
   refs are all dangling is auto-`unsupported` (no LLM call).
2. **Judge layer:** for surviving bullets, call the LLM-as-judge (`claude-opus-4-8`) with *only* the bullet
   text + the JSON of its referenced normalized resources, returning `supported | unsupported | partial`
   via structured output. Judge sees nothing else — it cannot "agree" using outside knowledge.

**Metric & report**
```python
class ClaimVerdict(BaseModel):
    bullet_text: str
    verdict: Literal["supported", "partial", "unsupported"]
    refs: list[SourceRef]

class FaithfulnessReport(BaseModel):
    score: float            # supported / total_claims
    total_claims: int
    verdicts: list[ClaimVerdict]
    passed: bool            # score >= THRESHOLD
```
- `THRESHOLD = 0.95` (config). `partial` counts as **not** supported for the score (strict).
- **Regenerate-on-failure:** if `passed` is False, `pipeline.summarize()` retries once with the failing
  bullets fed back as "these claims were unsupported — remove or correct them"; if it still fails, return
  the summary with `faithfulness.passed = False` surfaced in the UI rather than silently shipping it.
- Eval set = 10 fixture/synthea patients; `eval/` emits a pass/fail table (markdown) committed to the repo.

Acceptance (plan §3 / Phase 3): **≥95% of sampled claims trace to source.**

---

## 7. LLM wrapper contract 🟡

`clinical_core/llm/client.py` — a thin wrapper. Configure provider + model + key in `.env`; one function
does structured output. Use **LiteLLM** so any `provider/model` string works with no per-provider code.

```python
def complete(system: str, user: str, schema: type[BaseModelT]) -> BaseModelT: ...
```

- Reads `LLM_MODEL` (e.g. `anthropic/claude-opus-4-8`, `openai/gpt-4o`) + the matching API key from env.
  Default `anthropic/claude-opus-4-8`; set `LLM_MODEL=anthropic/claude-haiku-4-5` for cheap dev runs.
- Structured output via LiteLLM's `response_format=<pydantic schema>`, validated with Pydantic so `Summary`
  / judge verdicts come back typed.
- Log `input_tokens` / `output_tokens` / `cost_usd` per call (LiteLLM exposes cost); surface on `Summary`.

That's the whole wrapper. Don't add a provider abstraction layer — LiteLLM *is* the abstraction.

**Summarizer prompt** (`prompts.py`) must include, verbatim in spirit:
> "Use ONLY facts present in the provided patient data. Do not infer, assume, or add clinical information.
> For every bullet, populate `source_refs` with the resource(s) it came from. If a section has no data,
> return an empty bullet list — do NOT state that something is absent."

---

## 8. Fixtures 🔒

Three committed patients in `fixtures/`, chosen for coverage (not random):

| File | Must contain |
|---|---|
| `alpha.json` | multiple active conditions + current meds + ≥1 abnormal lab + ≥1 allergy (the "rich" case) |
| `beta.json` | sparse record — few resources, some missing dates (exercises §5 missing-data rules) |
| `gamma.json` | an explicit `no-known-allergies` AllergyIntolerance (exercises asserted-absence vs absence) |

`conftest.py` loads each as a `PatientRecord`. Snapshot tests (syrupy) pin the normalized output so
refactors can't silently change extraction. Pick these three from the generated `data/synthea/` set and
copy them in; record which source patients they were.

---

## 9. Acceptance harness (what "done" runs)

| Phase | Command that proves it |
|---|---|
| 0 | `uv run pytest` green; `uv run python -c "from clinical_core.fhir import load_bundle; print(load_bundle('fixtures/alpha.json').patient)"` |
| 1 | `uv run pytest tests/test_loader.py` — snapshot stable on all 3 fixtures |
| 2 | `uv run python -m summarizer.cli fixtures/alpha.json` — readable, 5 sections, correct order |
| 3 | `uv run python -m clinical_core.eval.faithfulness` — emits report, score ≥ 0.95 on eval set |
| 4 | `uv run streamlit run src/summarizer/app.py` — pick bundle → summary + faithfulness score |

End-to-end target (plan §3): **< 15s per patient.**
