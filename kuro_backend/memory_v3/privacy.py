"""Privacy and sensitivity helpers for Memory V3."""
from __future__ import annotations

import re


_HIGH_PATTERNS = [
    re.compile(r"\b(api[_ -]?key|secret|password|jwt|token)\b", re.IGNORECASE),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
]
_MEDIUM_PATTERNS = [
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    re.compile(r"\b(?:\+?\d[\d .-]{7,}\d)\b"),
]


def classify_sensitivity(content: str, explicit: str | None = None) -> str:
    if explicit in {"none", "low", "medium", "high"}:
        return explicit
    text = content or ""
    if any(pattern.search(text) for pattern in _HIGH_PATTERNS):
        return "high"
    if any(pattern.search(text) for pattern in _MEDIUM_PATTERNS):
        return "medium"
    return "low" if text.strip() else "none"


def redact_text(content: str) -> str:
    text = content or ""
    for pattern in _HIGH_PATTERNS:
        text = pattern.sub("[redacted]", text)
    for pattern in _MEDIUM_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text
