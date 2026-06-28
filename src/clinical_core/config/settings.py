"""Project settings, loaded from environment / .env via pydantic-settings.

CONTRACTS §4 / §6 / §7 — all tunables live here so filtered-view sizes, the
faithfulness threshold, and the LLM model can change without code edits.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM (CONTRACTS §7) -------------------------------------------------
    llm_model: str = "anthropic/claude-opus-4-8"
    api_key: str | None = None
    clinical_llm_temperature: float = 0.0
    clinical_llm_max_tokens: int = 4000

    # --- Faithfulness gate (CONTRACTS §6) -----------------------------------
    faithfulness_threshold: float = 0.95

    # --- Filtered-view sizes (CONTRACTS §4) ---------------------------------
    recent_encounters_n: int = 5
    abnormal_results_n: int = 10

    @property
    def analyzer_model(self) -> str:  # backwards-compat alias used by some call sites
        return self.llm_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton settings."""
    return Settings()
