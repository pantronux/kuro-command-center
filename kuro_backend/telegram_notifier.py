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

import logging
import os
import time
from typing import Final, Optional

logger = logging.getLogger(__name__)
logger.propagate = False

_TELEGRAM_API_BASE: Final[str] = "https://api.telegram.org"
_DEFAULT_TIMEOUT_S: Final[float] = 10.0
_MAX_TEXT_CHARS: Final[int] = 4000  # well under Telegram's 4096 hard limit


_INCONSISTENCY_TEMPLATE: Final[str] = (
    "Master, while I was operating as {persona}, I detected a research-data "
    "inconsistency from yesterday's discussion. {desc}. Shall I set it right?"
)


def _is_telegram_enabled() -> bool:
    """Worker-level kill switch; does NOT check config (that's send_message)."""
    return os.getenv("KURO_DREAMING_TELEGRAM_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


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


def _truncate(text: str) -> str:
    if not text:
        return ""
    # Ensure it's under Telegram's hard limit
    return text if len(text) <= 4000 else text[:3990] + "...[truncated]"


def send_message(
    text: str,
    *,
    parse_mode: Optional[str] = None,
    disable_notification: bool = False,
    dry_run: bool = False,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> bool:
    """Send ``text`` to the configured Telegram chat.

    Returns:
        True on HTTP 2xx, False otherwise (including config missing or dry_run).
    """
    if not text:
        return False
    if dry_run:
        logger.info("[TELEGRAM] dry_run=True payload=%r", _truncate(text))
        return False
    if not _is_telegram_enabled():
        logger.info("[TELEGRAM] disabled via KURO_DREAMING_TELEGRAM_ENABLED")
        return False

    token, chat_ids = _resolve_credentials()
    if not token or not chat_ids:
        logger.warning("[TELEGRAM] missing TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
        return False

    try:
        import requests
    except ImportError:
        logger.error("[TELEGRAM] requests library not installed")
        return False

    all_success = True
    url = f"{_TELEGRAM_API_BASE}/bot{token}/sendMessage"

    for cid in chat_ids:
        payload: dict = {
            "chat_id": cid,
            "text": _truncate(text),
            "disable_notification": bool(disable_notification),
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        success_for_cid = False
        for attempt in (1, 2, 3):
            try:
                resp = requests.post(url, json=payload, timeout=timeout_s)
            except Exception as exc:
                logger.warning("[TELEGRAM] attempt=%d network error: %s", attempt, exc)
                if attempt < 3:
                    time.sleep(0.5 * attempt)
                    continue
                break

            status = resp.status_code
            if 200 <= status < 300:
                success_for_cid = True
                break

            if status == 429:
                retry_after = int(resp.headers.get("retry-after", 5))
                logger.warning("[TELEGRAM] 429 Too Many Requests, sleeping %d s", retry_after)
                time.sleep(retry_after)
                continue

            if 500 <= status < 600 and attempt < 3:
                logger.warning("[TELEGRAM] attempt=%d 5xx (%d), retrying once", attempt, status)
                time.sleep(0.5)
                continue

            logger.warning("[TELEGRAM] failed status=%d body=%.200s", status, resp.text)
            break

        if not success_for_cid:
            all_success = False

    return all_success


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
]
