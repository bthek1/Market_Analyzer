"""Single entry point for resolving the runtime LLM configuration.

All call sites read LLM knobs through :func:`get_llm_config` instead of importing the
model (or reading ``settings.OLLAMA_*``) directly, so there is exactly one place that
handles the "table does not exist yet" bootstrap case (fresh DB, before the migration
runs, or tests that never touch the DB).
"""

from __future__ import annotations

from django.db.utils import DatabaseError

from .models import LLMSettings


def get_llm_config() -> LLMSettings:
    """Return the singleton LLM settings row.

    Falls back to an unsaved instance built from the model field defaults if the table
    is not available yet, so importing/booting the app never fails on a missing row.
    """
    try:
        return LLMSettings.get_solo()
    except DatabaseError:
        return LLMSettings()
