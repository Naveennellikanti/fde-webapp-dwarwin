"""Runtime-adjustable settings exposed to the UI.

Deliberately narrow: only *non-secret* knobs are adjustable at runtime. API keys are
never readable or writable through the API — they come from the server environment and
stay there. This is the same principle as a password manager: the app uses the
credential without ever exposing it to the client.

Prototype scope: these overrides are process-global. In a multi-tenant deployment they
would hang off the authenticated user/session instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import Settings


@dataclass
class RuntimeOverrides:
    schema_only: bool | None = None
    llm_backend: Literal["auto", "ollama", "groq"] | None = None
    sample_rows: int | None = None


_overrides = RuntimeOverrides()


def get_overrides() -> RuntimeOverrides:
    return _overrides


def update_overrides(
    *,
    schema_only: bool | None = None,
    llm_backend: str | None = None,
    sample_rows: int | None = None,
) -> RuntimeOverrides:
    if schema_only is not None:
        _overrides.schema_only = schema_only
    if llm_backend is not None:
        if llm_backend not in {"auto", "ollama", "groq"}:
            raise ValueError("llm_backend must be one of: auto, ollama, groq")
        _overrides.llm_backend = llm_backend  # type: ignore[assignment]
    if sample_rows is not None:
        _overrides.sample_rows = max(0, min(int(sample_rows), 10))
    return _overrides


def effective_settings(base: Settings) -> Settings:
    """Base config from the environment, with any UI overrides applied on top."""
    o = _overrides
    if o.schema_only is None and o.llm_backend is None and o.sample_rows is None:
        return base
    data = base.model_dump()
    if o.schema_only is not None:
        data["schema_only"] = o.schema_only
    if o.llm_backend is not None:
        data["llm_backend"] = o.llm_backend
    if o.sample_rows is not None:
        data["sample_rows"] = o.sample_rows
    return Settings(**data)
