"""Memory provenance tracking and attribution metadata."""

from __future__ import annotations

from typing import Any

from kuro_backend.memory_v2.memory_store import MemoryProvenance


def normalize_provenance(raw: Any = None, **overrides: Any) -> MemoryProvenance:
    """Return a sanitized provenance object from dict/model/free-form input."""
    data: dict[str, Any] = {}
    if isinstance(raw, MemoryProvenance):
        data.update(raw.model_dump())
    elif isinstance(raw, dict):
        data.update(raw)
    for key, value in overrides.items():
        if value is not None:
            data[key] = value
    allowed = {"session_id", "message_id", "document_id", "tool_call_id"}
    cleaned = {
        key: str(value).strip()[:256]
        for key, value in data.items()
        if key in allowed and str(value or "").strip()
    }
    return MemoryProvenance(**cleaned)


__all__ = ["normalize_provenance"]
