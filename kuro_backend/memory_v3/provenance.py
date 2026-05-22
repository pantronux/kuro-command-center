"""Provenance helpers for Memory V3."""
from __future__ import annotations

from typing import Any, Dict

from kuro_backend.memory_v3.schemas import MemoryEvent, MemoryWriteRequest


def build_provenance(request: MemoryWriteRequest, event: MemoryEvent) -> Dict[str, Any]:
    return {
        "source_type": request.source_type,
        "source_id": request.source_id,
        "event_id": event.event_id,
        "trace_id": request.trace_id,
        "metadata": dict(request.metadata or {}),
    }


def sanitize_provenance(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    data = dict(raw or {})
    forbidden_keys = {"api_key", "secret", "password", "token", "jwt"}
    return {
        str(key): value
        for key, value in data.items()
        if str(key).lower() not in forbidden_keys
    }
