"""Kuro AI V6.0 "Sovereign" — Telegram notifier.

Dedicated outbound Telegram client used by:
  - autonomous dreaming alerts (``dreaming_worker``).

Design goals:
- Zero raises into the caller; always returns bool so worker loops survive.
- Retry once on 5xx / network error; HTTP 4xx is final (bad chat id / token).
- Respect ``KURO_DREAMING_TELEGRAM_ENABLED`` kill switch + auto-disable when
  :mod:`config.settings` has no ``TELEGRAM_TOKEN`` / ``TELEGRAM_CHAT_ID``.
- ``dry_run=True`` logs the payload and skips the HTTP call — used by the
  CLI ``--dry-run`` flag and by tests.

--- Header Doc ---
Purpose: Resilient outbound Telegram notifier (bot token + chat id) for proactive events.
Caller: proactive_events._dispatch_async, dreaming_worker alerts.
Dependencies: requests/httpx, kuro_backend.config.
Main Functions: send_message(text, *, dry_run), is_configured(), _post_with_retry().
Side Effects: HTTPS call to api.telegram.org; logs redacted request/response.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Final, Optional

logger = logging.getLogger(__name__)
logger.propagate = False

_TELEGRAM_API_BASE: Final[str] = "https://api.telegram.org"
_DEFAULT_TIMEOUT_S: Final[float] = 10.0
_MAX_TEXT_CHARS: Final[int] = 4000  # well under Telegram's 4096 hard limit
_TELEGRAM_MAX_LEN: Final[int] = 4000
_TELEGRAM_TRUNC_SUFFIX: Final[str] = "\\n\\n📊 <i>Lihat laporan lengkap di Dashboard Kuro.</i>"


_INCONSISTENCY_TEMPLATE: Final[str] = (
    "Master, while I was operating as {persona}, I detected a research-data "
    "inconsistency from yesterday's discussion. {desc}. Shall I set it right?"
)


def _is_telegram_enabled() -> bool:
    """Worker-level kill switch; does NOT check config (that's send_message)."""
    raw = os.getenv(
        "KURO_TELEGRAM_ENABLED",
        os.getenv("KURO_DREAMING_TELEGRAM_ENABLED", "true"),
    )
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _resolve_credentials() -> tuple[Optional[str], Optional[str]]:
    """Return (token, chat_id) or (None, None) when config is missing."""
    try:
        from kuro_backend.config import settings
    except Exception as exc:
        logger.warning("[TELEGRAM] settings import failed: %s", exc)
        return None, None
    token = getattr(settings, "TELEGRAM_TOKEN", None) or os.getenv("TELEGRAM_TOKEN")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", None) or os.getenv("TELEGRAM_CHAT_ID")
    return (token or None), (chat_id or None)


def _resolve_chat_targets(chat_id: Optional[str]) -> list[str]:
    """Normalize chat-id targets from explicit value or env list."""
    _, configured = _resolve_credentials()
    raw = (chat_id or configured or "").strip()
    if not raw:
        return []
    if "," in raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [raw]


def _truncate(text: str) -> str:
    if not text:
        return ""
    # Ensure it's under Telegram's hard limit
    return text if len(text) <= 4000 else text[:3990] + "...[truncated]"


def _sanitize_for_telegram_limit(text: str) -> str:
    if not text:
        return ""
    if len(text) <= 4096:
        return text
    trimmed = text[:_TELEGRAM_MAX_LEN] + _TELEGRAM_TRUNC_SUFFIX
    logger.warning(
        "Telegram message truncated from %s to %s chars",
        len(text),
        len(trimmed),
    )
    return trimmed


def split_text_for_telegram(text: str, chunk_size: int = _TELEGRAM_MAX_LEN) -> list[str]:
    """Split long text into Telegram-safe chunks without silently dropping tail content."""
    if not text:
        return []
    safe_chunk_size = max(1, min(int(chunk_size), _TELEGRAM_MAX_LEN))
    return [text[i : i + safe_chunk_size] for i in range(0, len(text), safe_chunk_size)]


def _post_to_telegram_sync(payload: dict, timeout_s: float = _DEFAULT_TIMEOUT_S):
    import requests

    token, _ = _resolve_credentials()
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")
    url = f"{_TELEGRAM_API_BASE}/bot{token}/sendMessage"
    return requests.post(url, json=payload, timeout=timeout_s)


async def _post_to_telegram(payload: dict, timeout_s: float = _DEFAULT_TIMEOUT_S):
    return await asyncio.to_thread(_post_to_telegram_sync, payload, timeout_s)


async def send_message_with_retry(
    text: str,
    chat_id: str = None,
    max_attempts: int = 3,
    record_failure: bool = True,
) -> bool:
    """Retrying async Telegram sender with DLQ fallback on terminal failure."""
    if not text or not _is_telegram_enabled():
        return False
    targets = _resolve_chat_targets(chat_id)
    if not targets:
        logger.warning("[TELEGRAM] missing TELEGRAM_CHAT_ID")
        return False

    from kuro_backend import intelligence_db

    sent_all = True
    for target in targets:
        for chunk in split_text_for_telegram(text):
            payload = {
                "chat_id": target,
                "text": chunk,
            }
            last_error = None
            for attempt in range(max(1, int(max_attempts))):
                try:
                    resp = await _post_to_telegram(payload)
                    if 200 <= int(resp.status_code) < 300:
                        last_error = None
                        break
                    body = await asyncio.to_thread(lambda: resp.text)
                    last_error = f"HTTP {resp.status_code}: {body}"
                except Exception as exc:
                    last_error = str(exc)
                delay = (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)

            if last_error is not None:
                sent_all = False
                if record_failure:
                    try:
                        intelligence_db.log_failed_notification(
                            payload_json=json.dumps(payload, ensure_ascii=False),
                            error_message=last_error,
                        )
                    except Exception as db_exc:
                        logger.warning("[TELEGRAM] failed to enqueue DLQ row: %s", db_exc)
                logger.error(
                    "Telegram send failed after %s attempts: %s",
                    max_attempts,
                    last_error,
                )
    return sent_all


def send_message(
    text: str,
    *,
    parse_mode: Optional[str] = None,
    disable_notification: bool = False,
    dry_run: bool = False,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> bool:
    """Compatibility wrapper over async retry sender."""
    if not text:
        return False
    if dry_run:
        logger.info("[TELEGRAM] dry_run=True payload=%r", _truncate(text))
        return False
    if not _is_telegram_enabled():
        logger.info("[TELEGRAM] disabled via KURO_DREAMING_TELEGRAM_ENABLED")
        return False

    token, _ = _resolve_credentials()
    if not token:
        logger.warning("[TELEGRAM] missing TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
        return False

    _ = parse_mode  # parse mode intentionally ignored for free-form reports.
    _ = disable_notification  # preserved for signature compatibility.
    _ = timeout_s
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    if running_loop and running_loop.is_running():
        asyncio.create_task(send_message_with_retry(text))
        return True
    return asyncio.run(send_message_with_retry(text))


def send_dream_inconsistency(
    persona: str,
    short_description: str,
    *,
    finding_id: str = "",
    dry_run: bool = False,
) -> bool:
    """Proactive Telegram alert for an inconsistency finding.

    Uses the exact user-requested template. ``finding_id`` is logged for
    audit but is not included in the message body so the alert stays terse.
    """
    persona_label = (persona or "unknown").strip() or "unknown"
    desc = (short_description or "").strip()
    if not desc:
        logger.info("[TELEGRAM] skip inconsistency alert: empty description")
        return False
    message = _INCONSISTENCY_TEMPLATE.format(persona=persona_label, desc=desc)
    try:
        sent = send_message(message, dry_run=dry_run)
    except Exception as e:
        logger.warning("[TELEGRAM] send_dream_inconsistency failed: %s", e)
        sent = False
    logger.info(
        "[TELEGRAM] dream_inconsistency persona=%s finding=%s sent=%s",
        persona_label, finding_id or "-", sent,
    )
    return sent


__all__ = [
    "send_dream_inconsistency",
    "send_message",
    "send_message_with_retry",
    "split_text_for_telegram",
]
