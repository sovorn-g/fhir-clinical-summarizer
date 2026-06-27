"""Normalized intermediate models (CONTRACTS §3) + the ``PatientRecord`` aggregate (§4).

Every clinical fact carries a ``SourceRef`` so the faithfulness checker (§6) can trace each
summary claim back to the FHIR resource it came from. Provenance is the single most load-bearing
design decision in this kit — do not drop it.

These models are Pydantic v2 and intentionally provider-/LLM-agnostic. The summarizer and the
evaluator consume them; nothing here depends on the LLM wrapper.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from clinical_core.config.settings import get_settings

SourceRefType = Literal[
    "Condition",
    "MedicationRequest",
    "MedicationStatement",
    "Observation",
    "Encounter",
    "AllergyIntolerance",
    "Patient",
]


# --- provenance ---------------------------------------------------------------
class SourceRef(BaseModel):
    """Pointer from a clinical fact back to the FHIR resource it was derived from."""

    model_config = ConfigDict(frozen=True)

    resource_type: SourceRefType
    resource_id: str
    fhir_path: str | None = None  # optional slot for finer-grained provenance


# --- codeable concept ---------------------------------------------------------
class Coding(BaseModel):
    """Normalized CodeableConcept. ``display`` is always real (never invented)."""

    model_config = ConfigDict(frozen=True)

    system: str | None = None
    code: str | None = None
    display: str | None = None
    text: str | None = None

    def label(self) -> str:
        """Human-readable label: prefer display, then text, then code."""
        return self.display or self.text or self.code or "(unknown)"


# --- demographics -------------------------------------------------------------
class PatientDemographics(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str  # rendered "Given Family"
    gender: str | None = None
    birth_date: date | None = None
    age: int | None = None  # derived at load time, relative to today
    deceased: bool = False


# --- clinical facts -----------------------------------------------------------
class Condition(BaseModel):
    code: Coding
    clinical_status: str | None = (
        None  # active | recurrence | relapse | inactive | remission | resolved
    )
    verification_status: str | None = None
    onset_date: date | None = None
    recorded_date: date | None = None
    source: SourceRef


class Medication(BaseModel):
    """From MedicationRequest (and MedicationStatement if present)."""

    code: Coding
    status: str | None = None  # active | completed | stopped | ...
    dosage_text: str | None = None
    authored_on: date | None = None
    source: SourceRef


Interpretation = Literal["N", "H", "L", "HH", "LL", "A", "AA"]


class Observation(BaseModel):
    """Labs + vitals."""

    code: Coding
    value: float | str | None = None
    unit: str | None = None
    interpretation: Interpretation | None = None
    effective_date: date | None = None
    reference_range: str | None = None
    source: SourceRef


class Encounter(BaseModel):
    type: Coding | None = None
    encounter_class: str | None = None  # AMB, EMER, IMP, ...
    status: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    reason: Coding | None = None
    source: SourceRef


class Allergy(BaseModel):
    substance: Coding
    clinical_status: str | None = None
    criticality: str | None = None  # low | high | unable-to-assess
    reaction: str | None = None  # first manifestation text, if any
    source: SourceRef


# --- aggregate ----------------------------------------------------------------
class PatientRecord(BaseModel):
    """All normalized resources for one patient."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    patient: PatientDemographics
    conditions: list[Condition] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    encounters: list[Encounter] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)
    source_bundle_path: str

    # --- filtered views (CONTRACTS §4) — exact, stable rules ----------------
    _ACTIVE_CONDITION_STATUSES = {"active", "recurrence", "relapse"}

    @property
    def active_conditions(self) -> list[Condition]:
        """Clinical-status active/recurrence/relapse, onset_date desc (None last)."""
        items = [c for c in self.conditions if c.clinical_status in self._ACTIVE_CONDITION_STATUSES]
        return _sort_desc_none_last(items, key=lambda c: c.onset_date)

    @property
    def current_medications(self) -> list[Medication]:
        """status == active, authored_on desc (None last)."""
        items = [m for m in self.medications if m.status == "active"]
        return _sort_desc_none_last(items, key=lambda m: m.authored_on)

    @property
    def recent_encounters(self) -> list[Encounter]:
        """All encounters, period_start desc (None last), first N."""
        ordered = _sort_desc_none_last(self.encounters, key=lambda e: e.period_start)
        return ordered[: get_settings().recent_encounters_n]

    @property
    def abnormal_results(self) -> list[Observation]:
        """interpretation in {H,L,HH,LL,A,AA}, effective_date desc (None last), first N."""
        items = [
            o for o in self.observations if o.interpretation in {"H", "L", "HH", "LL", "A", "AA"}
        ]
        ordered = _sort_desc_none_last(items, key=lambda o: o.effective_date)
        return ordered[: get_settings().abnormal_results_n]


# --- helpers ------------------------------------------------------------------
_T = TypeVar("_T")


def _sort_desc_none_last(items: list[_T], key: Callable[[_T], date | None]) -> list[_T]:
    """Sort descending by ``key`` (a date), with None values placed last.

    Python can't compare ``None`` with ``date`` directly, so we encode "has a
    date" as the primary sort key (descending → real dates first) and use
    ``date.min`` as a stand-in for None so all None rows tie among themselves.
    """
    return sorted(items, key=lambda x: (key(x) is not None, key(x) or date.min), reverse=True)
