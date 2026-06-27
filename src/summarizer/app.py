"""Streamlit demo: pick/upload a FHIR bundle → summary + faithfulness score (CONTRACTS §9 Phase 4).

Run: ``uv run streamlit run src/summarizer/app.py``.

The app lets you choose a committed fixture or a generated Synthea bundle, or upload your own
FHIR R4 .json. It loads + normalizes the record, runs the summarization pipeline, and shows the
markdown summary together with the faithfulness report.

A ``Rules-only (no API key)`` toggle runs the pipeline with a deterministic mock summarizer and the
rules-only faithfulness layer, so the demo is fully functional offline — useful when you don't want
to burn tokens just to look at the UI.

Privacy: only synthetic (Synthea) data; no PHI is uploaded anywhere — all processing is local in this
Streamlit process, nothing is sent to a server except the LLM provider you configured (if any).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import streamlit as st

from clinical_core.fhir import load_bundle
from summarizer.render import render_record

log = logging.getLogger("summarizer.app")

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"
SYNTHEA = REPO / "data" / "synthea"


st.set_page_config(page_title="FHIR Clinical Summarizer", page_icon="🩺", layout="wide")
st.title("FHIR Clinical Summarizer")
st.caption("Synthetic FHIR R4 → concise, faithful clinician-ready summary. No PHI.")


@st.cache_data(show_spinner=False)
def list_bundles() -> dict[str, Path]:
    """Return {label: path} for committed fixtures + any generated Synthea bundles."""
    out: dict[str, Path] = {}
    for p in sorted(FIXTURES.glob("*.json")):
        out[f"fixture: {p.stem}"] = p
    for p in sorted(SYNTHEA.glob("*.json")):
        out[f"synthea: {p.stem[:40]}"] = p
    return out


def pick_bundle() -> Path | None:
    """Sidebar source picker; returns a path or None."""
    st.sidebar.subheader("1 — Patient bundle")
    source = st.sidebar.radio("Source", ["Pick from disk", "Upload .json"], horizontal=True)

    if source == "Pick from disk":
        bundles = list_bundles()
        if not bundles:
            st.sidebar.warning("No bundles found. Put files in fixtures/ or data/synthea/.")
            return None
        choice = st.sidebar.selectbox("Bundle", list(bundles.keys()))
        return bundles[choice]

    up = st.sidebar.file_uploader("FHIR R4 .json", type=["json"], accept_multiple_files=False)
    if up is None:
        return None
    tmp = Path(tempfile.gettempdir()) / f"upload_{up.name}"
    tmp.write_bytes(up.getvalue())
    return tmp


def build_mock_summary(record):
    """Rules-only offline summary (mirrors the eval runner's mock)."""
    from summarizer.models import Bullet, Section, Summary

    def sr(x):
        return [{"resource_type": x.source.resource_type, "resource_id": x.source.resource_id}]

    def section(heading, items, fmt):
        if items:
            it = items[0]
            return Section(heading=heading, bullets=[Bullet(text=fmt(it), source_refs=sr(it))])
        return Section(heading=heading, bullets=[], no_data=True)

    sections = [
        section("Problems", record.active_conditions, lambda c: f"Active: {c.code.label()}"),
        section("Medications", record.current_medications, lambda m: f"Current: {m.code.label()}"),
        section(
            "Recent Encounters",
            record.recent_encounters,
            lambda e: (
                f"{e.type.label() if e.type else 'visit'}"
                + (f" — {e.period_start}" if e.period_start else "")
            ),
        ),
        section(
            "Key Results",
            record.abnormal_results,
            lambda o: f"{o.code.label()} {o.value} {o.unit or ''} [{o.interpretation}]",
        ),
        section("Allergies", record.allergies, lambda a: f"Allergy: {a.substance.label()}"),
    ]
    return Summary(
        patient_id=record.patient.id,
        one_liner=f"{record.patient.name} — mock summary",
        sections=sections,
        model="mock (rules-only)",
    )


def main() -> None:  # pragma: no cover (UI)
    bundle_path = pick_bundle()
    rules_only = st.sidebar.checkbox(
        "Rules-only (no API key)",
        value=True,
        help="Use a deterministic mock summarizer + rules-only check "
        "so the demo runs offline. Uncheck to call the LLM.",
    )

    st.sidebar.markdown("---")
    run = st.sidebar.button(
        "Summarize", type="primary", disabled=bundle_path is None, use_container_width=True
    )

    if not run or bundle_path is None:
        st.info("Pick a bundle in the sidebar and hit **Summarize**.")
        return

    try:
        record = load_bundle(bundle_path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load bundle: {exc}")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Patient", record.patient.name)
    col2.metric("Age / Sex", f"{record.patient.age or '—'} / {record.patient.gender or '—'}")
    col3.metric("Active problems", len(record.active_conditions))
    col4.metric("Allergies", len(record.allergies))

    if st.toggle("Show rendered LLM context"):
        st.code(render_record(record), language="markdown")

    with st.spinner("Summarizing…"):
        if rules_only:
            summary = build_mock_summary(record)
            from clinical_core.eval.faithfulness import evaluate

            summary.faithfulness = evaluate(summary, record, judge=None)
        else:
            from summarizer.pipeline import summarize as run_pipeline

            summary = run_pipeline(record)

    st.subheader("Summary")
    st.markdown(summary.to_markdown())

    if summary.faithfulness is not None:
        fr = summary.faithfulness
        chip = "✅ passed" if fr.passed else "❌ below threshold"
        st.subheader(f"Faithfulness — {fr.score:.0%}  {chip}")
        st.caption(f"{fr.total_claims} claims, threshold 0.95, model {summary.model}")
        rows = [
            {"bullet": v.bullet_text, "verdict": v.verdict, "reason": v.reason or ""}
            for v in fr.verdicts
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        if summary.input_tokens or summary.output_tokens:
            st.caption(
                f"tokens in/out: {summary.input_tokens}/{summary.output_tokens}  "
                f"cost ${summary.cost_usd:.4f}"
            )

    st.download_button(
        "Download summary (.md)", summary.to_markdown(), file_name=f"{record.patient.id}_summary.md"
    )


if __name__ == "__main__":
    main()
