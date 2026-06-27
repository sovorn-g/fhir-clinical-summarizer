"""Shared pytest fixtures — loads the committed ``fixtures/`` as ``PatientRecord``s.

Per CONTRACTS §8 the three fixtures give coverage a random sample wouldn't:
  alpha — rich (multiple active conditions + current meds + abnormal results + allergies)
  beta  — sparse, with some dates stripped (exercises missing-data rules)
  gamma — an explicit no-known-allergies AllergyIntolerance (asserted absence vs absence)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinical_core.fhir import load_bundle

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str):
    return load_bundle(FIXTURES / f"{name}.json")


@pytest.fixture(scope="session")
def alpha_record():
    return _load("alpha")


@pytest.fixture(scope="session")
def beta_record():
    return _load("beta")


@pytest.fixture(scope="session")
def gamma_record():
    return _load("gamma")


@pytest.fixture(scope="session")
def fixture_records():
    return {name: _load(name) for name in ("alpha", "beta", "gamma")}
