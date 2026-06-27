"""Shared test helpers."""

from __future__ import annotations


def alpha_payload(record) -> dict:
    """A valid SummaryContent payload against the alpha record (all 5 sections, one empty)."""
    cond = record.active_conditions[0]
    med = record.current_medications[0]
    enc = record.recent_encounters[0]
    alg = record.allergies[0]

    def sr(x):
        return {"resource_type": x.source.resource_type, "resource_id": x.source.resource_id}

    sections = [
        {
            "heading": "Problems",
            "bullets": [{"text": f"Active: {cond.code.label()}", "source_refs": [sr(cond)]}],
        },
        {
            "heading": "Medications",
            "bullets": [{"text": f"Current: {med.code.label()}", "source_refs": [sr(med)]}],
        },
        {
            "heading": "Recent Encounters",
            "bullets": [
                {
                    "text": f"{enc.type.label() if enc.type else 'visit'} on {enc.period_start}",
                    "source_refs": [sr(enc)],
                }
            ],
        },
        {"heading": "Key Results", "bullets": []},
        {
            "heading": "Allergies",
            "bullets": [{"text": f"Allergy: {alg.substance.label()}", "source_refs": [sr(alg)]}],
        },
    ]
    return {
        "one_liner": "33yo M with active conditions and current medications.",
        "sections": sections,
    }
