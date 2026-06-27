"""FHIR R4 ingestion + normalization (CONTRACTS §3, §4)."""

from clinical_core.fhir.loader import PatientRecord, load_bundle
from clinical_core.fhir.models import (
    Allergy,
    Coding,
    Condition,
    Encounter,
    Interpretation,
    Medication,
    Observation,
    PatientDemographics,
    SourceRef,
)

__all__ = [
    "PatientRecord",
    "load_bundle",
    "SourceRef",
    "Coding",
    "PatientDemographics",
    "Condition",
    "Medication",
    "Observation",
    "Encounter",
    "Allergy",
    "Interpretation",
]
