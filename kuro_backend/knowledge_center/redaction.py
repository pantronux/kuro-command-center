"""Redaction helpers for approved knowledge responses."""
from __future__ import annotations

import re


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|jwt)\s*[:=]\s*['\"]?[^,\s;]+"
)
_SECRET_NAME_RE = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:API[_-]?KEY|SECRET|PASSWORD|PASSWD|TOKEN|JWT)[A-Z0-9_]*\b"
)
_RAW_PATH_RE = re.compile(r"(?i)(?<!\w)/(?:home|users|var|tmp|etc|opt|root|mnt)/[^\s,;]+")
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\[^\s,;]+")
_DB_FILE_RE = re.compile(r"(?i)\b[^\s,;]+(?:\.db|\.sqlite|\.sqlite3)\b")


def redact_public_text(value: str, *, max_chars: int = 4000) -> str:
    """Return response-safe text for KS/KKG callers."""
    cleaned = (value or "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    cleaned = cleaned.replace("\ufeff", "")
    cleaned = _RAW_PATH_RE.sub("[path]", cleaned)
    cleaned = _WINDOWS_PATH_RE.sub("[path]", cleaned)
    cleaned = _DB_FILE_RE.sub("[database-file]", cleaned)
    cleaned = _SECRET_ASSIGNMENT_RE.sub("[redacted]", cleaned)
    cleaned = _SECRET_NAME_RE.sub("[redacted]", cleaned)
    return " ".join(cleaned.split())[:max(1, int(max_chars))]
