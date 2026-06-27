"""clinical_core — shared kit for the clinical-AI portfolio.

Re-exported surface:
    from clinical_core.fhir import load_bundle, PatientRecord
    from clinical_core.llm import LLMClient
"""

from clinical_core.fhir.loader import PatientRecord, load_bundle
from clinical_core.llm.client import LLMClient

__all__ = ["PatientRecord", "load_bundle", "LLMClient"]

__version__ = "0.1.0"
