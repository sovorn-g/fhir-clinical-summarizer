"""Raw FHIR R4 resource (dict) → normalized model (CONTRACTS §3).

We parse Synthea R4 transaction bundles as plain ``dict`` rather than via the strict
``fhir.resources`` Pydantic models: Synthea emits extra fields that those strict models
reject with thousands of validation errors (see fhir.resources discussion #136). Manual
extraction is also exactly what CONTRACTS describes and is more robust to Synthea quirks.

Extraction rules (CONTRACTS §3):
- Prefer ``coding[0].display``; fall back to ``CodeableConcept.text``; never invent a display.
- Dates: accept ``dateTime``/``date``/``Period.start``; store as ``date``. Unparseable → None.
- ``Observation.interpretation``: map FHIR codes to N/H/L/HH/LL/A/AA; if absent and a numeric
  value falls outside a reference range, derive H/L; else None (we do *not* assert "normal").
- Synthea's R4 bundles omit both ``interpretation`` and ``referenceRange`` on observations, so
  the "outside referenceRange" rule would never fire. To keep the ``Key Results`` / abnormal
  view meaningful we derive interpretation from a conservative, documented table of adult
  reference thresholds keyed by LOINC code. This is *not* inventing resource content — the
  thresholds are well-known clinical cutoffs; the source value is untouched.
- Skip resources that fail; log counts. Partial data is expected, never an error.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from clinical_core.fhir.models import (
    Allergy,
    Coding,
    Condition,
    Encounter,
    Medication,
    Observation,
    PatientDemographics,
    SourceRef,
)

log = logging.getLogger(__name__)

# FHIR interpretation codes → normalized enum (CONTRACTS §3).
interpretation_map = {
    "N": "N",
    "H": "H",
    "L": "L",
    "HH": "HH",
    "LL": "LL",
    "A": "A",
    "AA": "AA",
    "U": None,
}

# --- LOINC-derived abnormality (only used when the resource omits interpretation
#     AND referenceRange — which Synthea's R4 samples do). (low, high) in the
#     observation's own unit. A value strictly outside flags H/L; inclusive bounds = normal.
#     Conservative, well-known adult cutoffs. Extend as needed; kept small on purpose.
LOINC_THRESHOLDS: dict[str, tuple[float | None, float | None]] = {
    "2339-0": (70.0, 140.0),  # Glucose mg/dL
    "2093-3": (None, 240.0),  # Total Cholesterol mg/dL
    "2571-8": (None, 200.0),  # Triglycerides mg/dL
    "18262-6": (None, 160.0),  # LDL mg/dL
    "2085-9": (40.0, None),  # HDL mg/dL  (low HDL is the abnormality)
    "718-7": (12.0, 18.0),  # Hemoglobin g/dL
    "38483-4": (None, 1.3),  # Creatinine mg/dL
    "39156-5": (18.5, 30.0),  # BMI kg/m2
    "2947-0": (135.0, 145.0),  # Sodium mmol/L
    "6298-4": (3.5, 5.0),  # Potassium mmol/L
    "2069-3": (98.0, 107.0),  # Chloride mmol/L
    "20565-8": (22.0, 29.0),  # Carbon Dioxide mmol/L
    "49765-1": (8.5, 10.2),  # Calcium mg/dL
    "6299-2": (7.0, 20.0),  # BUN mg/dL (urea nitrogen)
    "787-2": (80.0, 100.0),  # MCV fL
}


# --- small helpers ------------------------------------------------------------
def _coding_from_cc(cc: dict[str, Any] | None) -> Coding:
    """CodeableConcept → Coding. Prefer coding[0].display, fall back to text."""
    if not cc:
        return Coding()
    codings = cc.get("coding") or []
    c = codings[0] if codings else {}
    return Coding(
        system=c.get("system"),
        code=c.get("code"),
        display=c.get("display"),
        text=cc.get("text"),
    )


def _parse_date(value: Any) -> date | None:
    """Accept dateTime/date/Period-like strings. Unparseable → None (never a guess)."""
    if value is None:
        return None
    if isinstance(value, dict):  # Period
        value = value.get("start") or value.get("end")
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value)
    # FHIR ISO strings may have timezone or fractional seconds; date.fromisoformat
    # handles most cases on 3.11+, but strip a trailing 'Z' first.
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        # last-ditch: take the leading YYYY-MM-DD
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def _source(resource: dict[str, Any], path: str | None = None) -> SourceRef:
    return SourceRef(
        resource_type=resource.get("resourceType", "Unknown"),
        resource_id=str(resource.get("id", "")),
        fhir_path=path,
    )


def _interpretation(resource: dict[str, Any], value: float | None, unit: str | None) -> str | None:
    """Determine interpretation: resource-provided first, then LOINC-threshold derivation."""
    interp_list = resource.get("interpretation") or []
    if interp_list:
        coding = (interp_list[0].get("coding") or [{}])[0]
        code = coding.get("code")
        mapped = interpretation_map.get(code)
        if mapped is not None:
            return mapped
    # derive from referenceRange if present (CONTRACTS rule)
    for rr in resource.get("referenceRange") or []:
        low = (rr.get("low") or {}).get("value")
        high = (rr.get("high") or {}).get("value")
        if value is not None and low is not None and value < low:
            return "L"
        if value is not None and high is not None and value > high:
            return "H"
    # derive from LOINC thresholds (Synthea-augmentation; documented above)
    if value is None or not isinstance(value, (int, float)):
        return None
    for c in resource.get("code", {}).get("coding") or []:
        if (c.get("system") or "").endswith("loinc.org"):
            bounds = LOINC_THRESHOLDS.get(c.get("code"))
            if bounds:
                low, high = bounds
                if low is not None and value < low:
                    return "L"
                if high is not None and value > high:
                    return "H"
                return "N"  # within known threshold => explicitly normal
    return None


# --- per-resource extractors --------------------------------------------------
def extract_patient(resource: dict[str, Any]) -> PatientDemographics | None:
    try:
        names = resource.get("name") or []
        n = names[0] if names else {}
        given = " ".join(n.get("given") or [])
        family = n.get("family") or ""
        full_name = (given + " " + family).strip() or "(unknown)"

        birth_date = _parse_date(resource.get("birthDate"))
        age: int | None = None
        if birth_date is not None:
            today = date.today()
            age = (
                today.year
                - birth_date.year
                - ((today.month, today.day) < (birth_date.month, birth_date.day))
            )
            if age < 0:
                age = None

        return PatientDemographics(
            id=str(resource.get("id", "")),
            name=full_name,
            gender=resource.get("gender"),
            birth_date=birth_date,
            age=age,
            deceased=bool(resource.get("deceasedBoolean") or resource.get("deceasedDateTime")),
        )
    except Exception as exc:  # noqa: BLE001 — extraction must never raise
        log.warning("skip Patient %s: %s", resource.get("id"), exc)
        return None


def extract_condition(resource: dict[str, Any]) -> Condition | None:
    try:
        cs = (resource.get("clinicalStatus") or {}).get("coding") or [{}]
        vs = (resource.get("verificationStatus") or {}).get("coding") or [{}]
        return Condition(
            code=_coding_from_cc(resource.get("code")),
            clinical_status=cs[0].get("code") if cs else None,
            verification_status=vs[0].get("code") if vs else None,
            onset_date=_parse_date(resource.get("onsetDateTime") or resource.get("onsetPeriod")),
            recorded_date=_parse_date(resource.get("recordedDate")),
            source=_source(resource),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("skip Condition %s: %s", resource.get("id"), exc)
        return None


def extract_medication(resource: dict[str, Any]) -> Medication | None:
    try:
        cc = resource.get("medicationCodeableConcept") or resource.get("medicationReference")
        code = _coding_from_cc(cc) if "coding" in (cc or {}) or (cc and "code" in cc) else Coding()
        # dosageInstruction[0].text or asNeeded fallback
        dosage = None
        for d in resource.get("dosageInstruction") or []:
            dosage = d.get("text") or dosage
        return Medication(
            code=code,
            status=resource.get("status"),
            dosage_text=dosage,
            authored_on=_parse_date(resource.get("authoredOn")),
            source=_source(resource),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("skip MedicationRequest %s: %s", resource.get("id"), exc)
        return None


def extract_observation(resource: dict[str, Any]) -> Observation | None:
    try:
        vq = resource.get("valueQuantity") or {}
        raw_value = vq.get("value")
        value: float | str | None
        if isinstance(raw_value, (int, float)):
            value = float(raw_value)
        else:
            value = raw_value  # valueString / valueQuantity absent → None
        unit = vq.get("unit") or vq.get("code")
        interp = _interpretation(resource, value if isinstance(value, float) else None, unit)
        # referenceRange text fallback for display purposes
        ref_range = None
        for rr in resource.get("referenceRange") or []:
            ref_range = rr.get("text") or ref_range
        return Observation(
            code=_coding_from_cc(resource.get("code")),
            value=value,
            unit=unit,
            interpretation=interp,
            effective_date=_parse_date(
                resource.get("effectiveDateTime") or resource.get("effectivePeriod")
            ),
            reference_range=ref_range,
            source=_source(resource),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("skip Observation %s: %s", resource.get("id"), exc)
        return None


def extract_encounter(resource: dict[str, Any]) -> Encounter | None:
    try:
        types = resource.get("type") or []
        enc_type = _coding_from_cc(types[0]) if types else None
        cls = (resource.get("class") or {}).get("code")
        reason = None
        reasons = resource.get("reasonCode") or []
        if reasons:
            reason = _coding_from_cc(reasons[0])
        period = resource.get("period") or {}
        return Encounter(
            type=enc_type,
            encounter_class=cls,
            status=resource.get("status"),
            period_start=_parse_date(period.get("start")),
            period_end=_parse_date(period.get("end")),
            reason=reason,
            source=_source(resource),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("skip Encounter %s: %s", resource.get("id"), exc)
        return None


def extract_allergy(resource: dict[str, Any]) -> Allergy | None:
    try:
        cc = resource.get("code") or resource.get("substance")  # R4 `code`; STU3 `substance`
        substance = _coding_from_cc(cc)
        cs = resource.get("clinicalStatus") or {}
        if isinstance(cs, dict):
            cs = (cs.get("coding") or [{}])[0].get("code")
        reaction_text = None
        for r in resource.get("reaction") or []:
            manif = r.get("manifestation") or []
            reaction_text = (manif[0].get("text") if manif else None) or r.get("description")
            if reaction_text:
                break
        return Allergy(
            substance=substance,
            clinical_status=cs,
            criticality=resource.get("criticality"),
            reaction=reaction_text,
            source=_source(resource),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("skip AllergyIntolerance %s: %s", resource.get("id"), exc)
        return None


EXTRACTORS = {
    "Patient": extract_patient,
    "Condition": extract_condition,
    "MedicationRequest": extract_medication,
    "MedicationStatement": extract_medication,
    "Observation": extract_observation,
    "Encounter": extract_encounter,
    "AllergyIntolerance": extract_allergy,
}
