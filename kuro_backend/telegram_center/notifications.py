"""Notification hygiene primitives for Telegram delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pytz

from kuro_backend.config import settings

Severity = Literal["info", "warning", "critical"]


@dataclass
class DigestEvent:
    severity: Severity
    title: str
    body: str
    created_at: str


_DIGEST_BUFFER: list[DigestEvent] = []


def reset_digest_for_tests() -> None:
    _DIGEST_BUFFER.clear()


def should_send_immediately(severity: Severity) -> bool:
    return severity == "critical" and bool(
        getattr(settings, "KURO_TELEGRAM_CRITICAL_INSTANT", True)
    )


def queue_or_send_event(severity: Severity, title: str, body: str) -> bool:
    """Return True when caller should send immediately; otherwise buffer for digest."""
    if should_send_immediately(severity):
        return True
    _DIGEST_BUFFER.append(
        DigestEvent(
            severity=severity,
            title=title,
            body=body,
            created_at=_now_label(),
        )
    )
    return False


def build_digest_text() -> str:
    if not _DIGEST_BUFFER:
        return "Kuro Telegram Digest\nNo buffered events."
    lines = ["Kuro Telegram Digest", f"Events: {len(_DIGEST_BUFFER)}", ""]
    for event in list(_DIGEST_BUFFER):
        lines.append(f"[{event.severity.upper()}] {event.title}")
        lines.append(event.body)
        lines.append(f"At: {event.created_at}")
        lines.append("")
    return "\n".join(lines).strip()


def flush_digest() -> str:
    text = build_digest_text()
    _DIGEST_BUFFER.clear()
    return text


def _now_label() -> str:
    tz = pytz.timezone(getattr(settings, "TIMEZONE", "Asia/Jakarta") or "Asia/Jakarta")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M WIB")
