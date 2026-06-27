"""Bundle → ``PatientRecord`` (CONTRACTS §4)."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from clinical_core.fhir.extract import EXTRACTORS
from clinical_core.fhir.models import (
    PatientDemographics,
    PatientRecord,
)

log = logging.getLogger(__name__)


def load_bundle(path: str | Path) -> PatientRecord:
    """Load one FHIR R4 transaction/batch bundle into a ``PatientRecord``.

    Resources are extracted best-effort: malformed ones are skipped (logged by count),
    matching CONTRACTS' "partial data is expected, never an error".
    """
    path = Path(path)
    bundle: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    entries = bundle.get("entry") or []

    buckets: dict[str, list] = {
        "Condition": [],
        "Medication": [],
        "Observation": [],
        "Encounter": [],
        "Allergy": [],
    }
    patient: PatientDemographics | None = None
    skipped: Counter[str] = Counter()

    for entry in entries:
        resource = entry.get("resource") or {}
        rt = resource.get("resourceType")
        extractor = EXTRACTORS.get(rt)
        if extractor is None:
            continue
        try:
            result = extractor(resource)
        except Exception as exc:  # noqa: BLE001 — never raise on a bad resource
            skipped[rt] += 1
            log.debug("extractor raised for %s: %s", rt, exc)
            continue
        if result is None:
            skipped[rt] += 1
            continue
        if rt == "Patient":
            patient = result  # type: ignore[assignment]
        else:
            bucket = _ROUTE_KEY.get(rt)
            if bucket is not None:
                buckets[bucket].append(result)

    if skipped:
        log.info("skipped resources while loading %s: %s", path.name, dict(skipped))

    if patient is None:
        raise ValueError(f"{path}: bundle has no usable Patient resource")

    return PatientRecord(
        patient=patient,
        conditions=buckets["Condition"],
        medications=buckets["Medication"],
        observations=buckets["Observation"],
        encounters=buckets["Encounter"],
        allergies=buckets["Allergy"],
        source_bundle_path=str(path),
    )


_ROUTE_KEY = {
    "Condition": "Condition",
    "MedicationRequest": "Medication",
    "MedicationStatement": "Medication",
    "Observation": "Observation",
    "Encounter": "Encounter",
    "AllergyIntolerance": "Allergy",
}
