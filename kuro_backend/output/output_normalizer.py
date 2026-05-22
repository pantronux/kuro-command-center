"""Structured output normalization helpers."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


def normalize_output(value: Any) -> str:
    """Return a stable text representation for structured output payloads."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def normalize_json_object(value: Any) -> dict[str, Any]:
    """Coerce a supported payload into a JSON object dictionary."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Structured output payload must be a JSON object")
