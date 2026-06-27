"""Render a ``PatientRecord`` into a compact, provenance-tagged LLM context (CONTRACTS §4/§7).

Every line is tagged ``[ResourceType/<id>]`` so the model can populate ``source_refs`` with the
exact resource it drew a bullet from. The renderer — not the model — decides what counts as
"no data" for a section (CONTRACTS §5 missing-data trap).
"""

from __future__ import annotations

from clinical_core.fhir.models import PatientRecord


def _ref_line(ref) -> str:
    return f"[{ref.resource_type}/{ref.resource_id}]"


def render_record(record: PatientRecord) -> str:
    lines: list[str] = []

    p = record.patient
    lines.append(f"# Patient {p.name} ({p.id})")
    bits = []
    if p.gender:
        bits.append(f"sex={p.gender}")
    if p.age is not None:
        bits.append(f"age={p.age}")
    if p.birth_date:
        bits.append(f"DOB={p.birth_date}")
    if p.deceased:
        bits.append("deceased=true")
    if bits:
        lines.append("demographics: " + ", ".join(bits))
    lines.append("")

    def section(title: str, items, fmt):
        lines.append(f"## {title}")
        if not items:
            lines.append("(no data)")
        else:
            for item in items:
                lines.append(f"{_ref_line(item.source)} {fmt(item)}")
        lines.append("")

    section(
        "Active Conditions",
        sorted(
            record.active_conditions,
            key=lambda c: c.clinical_status or "",
        ),
        lambda c: (
            f"{c.code.label()} — status={c.clinical_status}"
            + (f", onset={c.onset_date}" if c.onset_date else "")
            + (f", recorded={c.recorded_date}" if c.recorded_date else "")
        ),
    )
    section(
        "Current Medications",
        record.current_medications,
        lambda m: (
            f"{m.code.label()}"
            + (f" — {m.dosage_text}" if m.dosage_text else "")
            + (f", authored={m.authored_on}" if m.authored_on else "")
        ),
    )
    section(
        "Recent Encounters",
        record.recent_encounters,
        lambda e: (
            f"{e.type.label() if e.type else '(encounter)'}"
            + (f" — class={e.encounter_class}" if e.encounter_class else "")
            + (f", status={e.status}" if e.status else "")
            + (f", {e.period_start}" if e.period_start else "")
            + (f" → {e.period_end}" if e.period_end else "")
            + (f", reason={e.reason.label()}" if e.reason else "")
        ),
    )
    section(
        "Key Results (abnormal)",
        record.abnormal_results,
        lambda o: (
            f"{o.code.label()} = {o.value}{(' ' + o.unit) if o.unit else ''}"
            + (f" [{o.interpretation}]" if o.interpretation else "")
            + (f", eff={o.effective_date}" if o.effective_date else "")
        ),
    )
    section(
        "Allergies",
        record.allergies,
        lambda a: (
            f"{a.substance.label()}"
            + (f" — status={a.clinical_status}" if a.clinical_status else "")
            + (f", criticality={a.criticality}" if a.criticality else "")
            + (f", reaction={a.reaction}" if a.reaction else "")
        ),
    )

    return "\n".join(lines).strip() + "\n"
