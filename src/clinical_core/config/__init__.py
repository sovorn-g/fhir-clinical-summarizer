"""Configuration via pydantic-settings (reads .env)."""

from clinical_core.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
