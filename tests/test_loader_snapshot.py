"""Phase 1: snapshot tests pinning normalized ``PatientRecord`` output (CONTRACTS §1/§8).

Syrupy stores serialized snapshots in ``tests/__snapshots__/``. Run ``pytest --snapshot-update``
after an *intentional* extraction change; a refactor that silently changes normalization will fail
these and force a review.

We snapshot a deterministic dict form (dates ISO-formatted, lists in filtered-view order) of each
fixture so the artifact is human-reviewable, not a 2000-resource dump.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from clinical_core.fhir import load_bundle

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _snap(record) -> dict:
    def coding(c):
        return {"system": c.system, "code": c.code, "display": c.display, "text": c.text}

    def d(v: date | None) -> str | None:
        return v.isoformat() if isinstance(v, date) else v

    def cond(c):
        return {
            "code": coding(c.code),
            "clinical_status": c.clinical_status,
            "verification_status": c.verification_status,
            "onset_date": d(c.onset_date),
            "recorded_date": d(c.recorded_date),
            "source_type": c.source.resource_type,
            "source_id": c.source.resource_id,
        }

    def med(m):
        return {
            "code": coding(m.code),
            "status": m.status,
            "dosage_text": m.dosage_text,
            "authored_on": d(m.authored_on),
            "source_id": m.source.resource_id,
        }

    def obs(o):
        return {
            "code": coding(o.code),
            "value": o.value,
            "unit": o.unit,
            "interpretation": o.interpretation,
            "effective_date": d(o.effective_date),
            "source_id": o.source.resource_id,
        }

    def enc(e):
        return {
            "type": coding(e.type) if e.type else None,
            "class": e.encounter_class,
            "status": e.status,
            "period_start": d(e.period_start),
            "period_end": d(e.period_end),
            "reason": coding(e.reason) if e.reason else None,
            "source_id": e.source.resource_id,
        }

    def alg(a):
        return {
            "substance": coding(a.substance),
            "clinical_status": a.clinical_status,
            "criticality": a.criticality,
            "reaction": a.reaction,
            "source_id": a.source.resource_id,
        }

    p = record.patient
    return {
        "patient": {
            "id": p.id,
            "name": p.name,
            "gender": p.gender,
            "birth_date": d(p.birth_date),
            "deceased": p.deceased,
        },
        "active_conditions": [cond(c) for c in record.active_conditions],
        "current_medications": [med(m) for m in record.current_medications],
        "recent_encounters": [enc(e) for e in record.recent_encounters],
        "abnormal_results": [obs(o) for o in record.abnormal_results],
        "allergies": [alg(a) for a in record.allergies],
        "counts": {
            "conditions": len(record.conditions),
            "medications": len(record.medications),
            "observations": len(record.observations),
            "encounters": len(record.encounters),
            "allergies": len(record.allergies),
        },
    }


def test_alpha_snapshot(snapshot: SnapshotAssertion):
    rec = load_bundle(FIXTURES / "alpha.json")
    assert _snap(rec) == snapshot


def test_beta_snapshot(snapshot: SnapshotAssertion):
    rec = load_bundle(FIXTURES / "beta.json")
    assert _snap(rec) == snapshot


def test_gamma_snapshot(snapshot: SnapshotAssertion):
    rec = load_bundle(FIXTURES / "gamma.json")
    assert _snap(rec) == snapshot


def test_all_provenance_non_empty(fixture_records):
    # every normalized fact must trace to a non-empty SourceRef (CONTRACTS §3)
    for _name, rec in fixture_records.items():
        for coll in (
            rec.conditions,
            rec.medications,
            rec.observations,
            rec.encounters,
            rec.allergies,
        ):
            for item in coll:
                assert item.source.resource_id, f"{item} missing source id"
                assert item.source.resource_type
