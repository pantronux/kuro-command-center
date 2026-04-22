"""Kuro AI V6.1 "Sovereign" — UI mode keyword router.

Detects natural-language "mode" commands in the chat pipeline (primarily
English as of V6.1, with legacy Bahasa Indonesia patterns retained so old
habits keep working) and returns the canonical :mod:`dashboard_broadcast`
UI command so the caller can relay it to the frontend.

Handlers must:

1. Call :func:`detect_mode_command` before invoking the LangGraph core.
2. When a match is returned, schedule a UI_COMMAND broadcast and either
   forward the cleaned remainder to the graph or reply with the built-in
   acknowledgement (see :func:`acknowledgement`) when the remainder is
   empty.

This mirrors the lightweight pattern used by ``route_telegram_persona``
in ``main.py`` — zero LLM calls, zero DB hits.

--- Header Doc ---
Purpose: Zero-cost keyword router for chat-initiated UI mode commands.
Caller: main.py chat routes before LangGraph dispatch.
Dependencies: dashboard_broadcast command constants.
Main Functions: detect_mode_command(text) -> (command, remainder, confirmation).
Side Effects: None (pure regex).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Canonical command -> list of regex patterns (case-insensitive, word
# boundary aware). Longer patterns must come first so "mode riset"
# doesn't accidentally match "mode" alone.
_MODE_PATTERNS: Dict[str, List[str]] = {
    "RESEARCH_MODE": [
        # V6.1 English triggers (Sebastian register)
        r"activate\s+research\s+mode",
        r"enter\s+research\s+mode",
        r"engage\s+research\s+mode",
        r"research\s+mode",
        r"mode\s+research",
        # Legacy BI
        r"mode\s+riset",
        r"mode\s+peneliti(?:an)?",
    ],
    "CINEMA_MODE": [
        r"activate\s+cinema\s+mode",
        r"switch\s+to\s+cinema(?:\s+mode)?",
        r"engage\s+cinema\s+mode",
        r"cinema\s+mode",
        r"movie\s+mode",
        # Legacy BI
        r"mode\s+cinema",
        r"mode\s+bioskop",
    ],
    "HUD_MODE": [
        r"activate\s+hud(?:\s+mode)?",
        r"switch\s+to\s+hud(?:\s+mode)?",
        r"engage\s+hud(?:\s+mode)?",
        r"hud\s+mode",
        r"jarvis\s+mode",
        # Legacy BI
        r"mode\s+hud",
        r"mode\s+jarvis",
    ],
    "NORMAL_MODE": [
        r"stand\s+down",
        r"resume\s+normal(?:\s+mode)?",
        r"return\s+to\s+normal(?:\s+mode)?",
        r"normal\s+mode",
        r"exit\s+(?:hud|research|cinema|jarvis)\s+mode",
        # Legacy BI
        r"mode\s+normal",
        r"kembali\s+normal",
        r"keluar\s+(?:dari\s+)?mode\s+(?:hud|riset|cinema|jarvis)",
        r"keluar\s+(?:dari\s+)?(?:hud|research|cinema|jarvis)\s+mode",
    ],
    "STATUS_TICKER": [
        r"system\s+status",
        r"status\s+report",
        r"report\s+status",
        r"sentinel\s+status",
    ],
}

_COMPILED: Dict[str, List[re.Pattern[str]]] = {
    cmd: [re.compile(p, re.IGNORECASE) for p in patterns]
    for cmd, patterns in _MODE_PATTERNS.items()
}

# Optional "kuro, <mode>" prefix. Also accepts comma + space variations.
_ADDRESS_PREFIX = re.compile(
    r"^\s*(?:kuro|hey\s+kuro|oi\s+kuro)[\s,:-]+",
    re.IGNORECASE,
)


def _strip_address_prefix(text: str) -> str:
    return _ADDRESS_PREFIX.sub("", text, count=1).strip()


def detect_mode_command(text: str) -> Optional[Tuple[str, str]]:
    """Return ``(command, cleaned_text)`` when ``text`` contains a mode phrase.

    ``cleaned_text`` has the matched phrase removed so the caller can
    forward any remaining question to the LangGraph core. When the user
    said nothing else, ``cleaned_text`` is an empty string and the caller
    should respond with :func:`acknowledgement`.
    """
    if not text or not isinstance(text, str):
        return None
    stripped = _strip_address_prefix(text)
    # Evaluate commands in a stable priority so ambiguous multi-mode
    # sentences resolve predictably. Explicit NORMAL_MODE wins over the
    # others so "exit HUD mode" / "keluar dari HUD mode" doesn't match
    # HUD_MODE first. STATUS_TICKER is evaluated last so "system status
    # inside HUD mode" still prefers HUD_MODE.
    order = ("NORMAL_MODE", "HUD_MODE", "RESEARCH_MODE", "CINEMA_MODE", "STATUS_TICKER")
    for command in order:
        patterns = _COMPILED.get(command) or []
        for pattern in patterns:
            match = pattern.search(stripped)
            if match:
                cleaned = (
                    stripped[: match.start()] + stripped[match.end():]
                ).strip(" ,.;:!?-")
                return command, cleaned
    return None


_ACK_TEMPLATES: Dict[str, str] = {
    "HUD_MODE": (
        "Very well, Master. HUD Mode engaged — the tactical Jarvis theme has "
        "been dispatched to your dashboard."
    ),
    "RESEARCH_MODE": (
        "At your service, Master. Research Mode is active; the dashboard has "
        "adopted its research layout and the latest server-status digest has "
        "been forwarded to the HUD."
    ),
    "CINEMA_MODE": (
        "Cinema Mode engaged, Master. The dimmed cinematic theme has been "
        "delivered to your dashboard — do enjoy the viewing."
    ),
    "NORMAL_MODE": (
        "As you wish, Master. Returning the dashboard to Normal Mode; the "
        "theme has been reset."
    ),
    "STATUS_TICKER": (
        "The status ticker has been dispatched to your dashboard, Master."
    ),
}


def acknowledgement(command: str) -> str:
    """Return the short built-in acknowledgement for ``command``."""
    return _ACK_TEMPLATES.get(
        command.upper(),
        "UI command acknowledged, Master.",
    )


__all__ = [
    "acknowledgement",
    "detect_mode_command",
]
