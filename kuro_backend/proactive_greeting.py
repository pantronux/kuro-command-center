"""Kuro AI V6.0 "Sovereign" — Proactive dashboard greeting.

When the master opens the dashboard, Kuro should whisper a butler-flavoured
welcome at most once per calendar day. This module encapsulates the cooldown
check, the per-client UI_COMMAND send, and the SQLite persistence so the
``/ws/dashboard`` handler stays a one-liner.

Configuration (all optional; the defaults are Sebastian-safe):

- ``KURO_PROACTIVE_GREETING_ENABLED``       (default ``true``)
- ``KURO_PROACTIVE_GREETING_TEXT``          (default English welcome)
- ``KURO_PROACTIVE_GREETING_COOLDOWN_DAYS`` (default ``1``)
- ``KURO_PROACTIVE_GREETING_LANG``          (default ``en`` — matches Alan)

The function never raises; a broken greeting must never take down the
WebSocket handshake.

--- Header Doc ---
Purpose: One-per-day butler greeting push to the dashboard UI on connect.
Caller: main.py /ws/dashboard handler.
Dependencies: dashboard_broadcast, voice_service (optional TTS line), sqlite for cooldown state.
Main Functions: maybe_send_greeting(), _greeting_due_today(), _record_sent().
Side Effects: Writes cooldown row to short-term DB, sends UI_COMMAND over WS, optional TTS synthesis.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from starlette.websockets import WebSocket

from kuro_backend import auth_db
from kuro_backend import dashboard_broadcast

logger = logging.getLogger(__name__)

_DEFAULT_TEXT: str = (
    "Welcome back, Master Pantronux. All systems are operating normally."
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _greeting_text() -> str:
    raw = os.getenv("KURO_PROACTIVE_GREETING_TEXT")
    if raw and raw.strip():
        return raw.strip()
    return _DEFAULT_TEXT


def _greeting_lang() -> str:
    raw = (os.getenv("KURO_PROACTIVE_GREETING_LANG") or "en").strip().lower()
    return raw or "en"


async def maybe_send(ws: WebSocket, username: Optional[str]) -> bool:
    """Send the daily greeting to ``ws`` if cooldown permits.

    Returns True when a greeting frame was actually dispatched. Returns
    False (and logs at debug) when the feature is disabled, the user is
    unknown, the cooldown blocks, or the WS send failed.
    """
    if not _env_bool("KURO_PROACTIVE_GREETING_ENABLED", True):
        logger.debug("[GREETING] disabled via env")
        return False
    user = (username or "").strip()
    if not user:
        logger.debug("[GREETING] no username on ws; skipping")
        return False

    cooldown = _env_int("KURO_PROACTIVE_GREETING_COOLDOWN_DAYS", 1)
    try:
        if auth_db.greeting_sent_within(user, cooldown):
            logger.debug("[GREETING] within cooldown for user=%s", user)
            return False
    except Exception as exc:
        logger.warning("[GREETING] cooldown check failed: %s", exc)
        # Fail-open: one extra greeting is better than a silent boot.

    text = _greeting_text()
    lang = _greeting_lang()
    payload = {"text": text, "lang": lang}
    try:
        delivered = await dashboard_broadcast.send_ui_command_to(
            ws, "GREETING", payload,
        )
    except Exception as exc:
        logger.warning("[GREETING] send failed: %s", exc)
        delivered = False

    if delivered:
        try:
            auth_db.record_greeting_sent(user)
        except Exception as exc:
            logger.warning("[GREETING] record failed: %s", exc)
    return delivered


__all__ = ["maybe_send"]
