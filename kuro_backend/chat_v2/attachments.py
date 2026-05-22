"""Attachment and artifact reference helpers for Chat V2."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List


_RAW_PATH_RE = re.compile(r"(?i)(?<!\w)/(?:home|users|var|tmp|etc|opt|root|mnt)/[^\s,;]+")
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\[^\s,;]+")
_SECRET_RE = re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|jwt)\b")


def _safe_text(value: Any, *, max_len: int = 256) -> str:
    text = str(value or "")
    text = _RAW_PATH_RE.sub("[path]", text)
    text = _WINDOWS_PATH_RE.sub("[path]", text)
    if _SECRET_RE.search(text):
        text = "[redacted]"
    return text.strip()[:max_len]


def sanitize_artifact_refs(raw_refs: Iterable[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    """Return frontend-safe artifact refs without raw server paths."""
    safe_refs: List[Dict[str, Any]] = []
    for raw in raw_refs or []:
        if not isinstance(raw, dict):
            continue
        ref: Dict[str, Any] = {
            "type": _safe_text(raw.get("type") or "attachment", max_len=64),
        }
        original = raw.get("original_filename")
        stored = raw.get("stored_filename") or raw.get("filename")
        if original:
            ref["original_filename"] = os.path.basename(_safe_text(original))
        if stored:
            ref["stored_filename"] = os.path.basename(_safe_text(stored))
        if raw.get("content_type"):
            ref["content_type"] = _safe_text(raw.get("content_type"), max_len=128)
        if raw.get("size_bytes") is not None:
            try:
                ref["size_bytes"] = int(raw.get("size_bytes") or 0)
            except (TypeError, ValueError):
                ref["size_bytes"] = 0
        if raw.get("sha256"):
            ref["sha256"] = _safe_text(raw.get("sha256"), max_len=128)
        safe_refs.append(ref)
    return safe_refs


def sanitize_message_payload(message: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(message or {})
    cleaned.pop("stored_path", None)
    cleaned.pop("archive_path", None)
    cleaned.pop("path", None)
    cleaned["artifact_refs"] = sanitize_artifact_refs(cleaned.get("artifact_refs") or [])
    return cleaned
