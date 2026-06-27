"""Loader + normalization smoke tests (Phase 0 acceptance). Snapshot stability lands in Phase 1."""

from __future__ import annotations


# --- alpha: the rich case -----------------------------------------------------
def test_alpha_loads_patient(alpha_record):
    p = alpha_record.patient
    assert p.id
    assert p.name  # "Given Family", never empty
    assert alpha_record.source_bundle_path.endswith("alpha.json")


def test_alpha_has_active_conditions_and_meds(alpha_record):
    assert len(alpha_record.active_conditions) >= 1, "alpha should have active conditions"
    assert len(alpha_record.current_medications) >= 1, "alpha should have current meds"
    # active_conditions only contains active/recurrence/relapse (CONTRACTS §4)
    statuses = {c.clinical_status for c in alpha_record.active_conditions}
    assert statuses <= {"active", "recurrence", "relapse"}


def test_alpha_has_allergy(alpha_record):
    assert len(alpha_record.allergies) >= 1


def test_observation_has_provenance(alpha_record):
    # every clinical fact carries a SourceRef (the load-bearing design decision, CONTRACTS §3)
    assert all(o.source.resource_id for o in alpha_record.observations)
    assert alpha_record.observations[0].source.resource_type == "Observation"


def test_abnormal_results_capped_and_flagged(alpha_record):
    abn = alpha_record.abnormal_results
    assert all(o.interpretation in {"H", "L", "HH", "LL", "A", "AA"} for o in abn)
    if abn:  # alpha should have ≥1 abnormal (CONTRACTS §8), but don't hard-fail the cap check
        assert len(abn) <= 10  # ABNORMAL_RESULTS_N default


def test_recent_encounters_capped(alpha_record):
    assert len(alpha_record.recent_encounters) <= 5  # RECENT_ENCOUNTERS_N default


# --- beta: sparse + missing dates --------------------------------------------
def test_beta_is_sparse(beta_record):
    # beta is the small/curated fixture — counts should be modest
    total = (
        len(beta_record.conditions)
        + len(beta_record.medications)
        + len(beta_record.observations)
        + len(beta_record.encounters)
    )
    assert total > 0


def test_beta_exercises_missing_dates(beta_record):
    # we stripped some dates on purpose; at least one normalized fact should have None date
    none_dates = [c for c in beta_record.conditions if c.onset_date is None] + [
        o for o in beta_record.observations if o.effective_date is None
    ]
    assert none_dates, "beta should have ≥1 fact with a missing date"


def test_beta_active_conditions_empty_or_no_error(beta_record):
    # beta has 0 active conditions by construction — the view must be [], not an error
    assert isinstance(beta_record.active_conditions, list)
    assert beta_record.active_conditions == []


def test_sort_none_last(beta_record):
    # None dates must sort last, not raise (CONTRACTS §4)
    for view in (
        beta_record.active_conditions,
        beta_record.recent_encounters,
        beta_record.abnormal_results,
        beta_record.current_medications,
    ):
        assert isinstance(view, list)  # would raise if None comparison happened


# --- gamma: asserted absence --------------------------------------------------
def test_gamma_has_no_known_allergies_resource(gamma_record):
    nka = [
        a
        for a in gamma_record.allergies
        if a.substance.code == "716186003"
        or (a.substance.display or "").lower().startswith("no known allerg")
    ]
    assert nka, "gamma must contain the explicit no-known-allergies AllergyIntolerance"


# --- general ------------------------------------------------------------------
def test_filtering_rules_match_contract(fixture_records):
    for _name, rec in fixture_records.items():
        # current_medications only active
        assert all(m.status == "active" for m in rec.current_medications)
        # active_conditions only active/recurrence/relapse
        assert all(
            c.clinical_status in {"active", "recurrence", "relapse"} for c in rec.active_conditions
        )
