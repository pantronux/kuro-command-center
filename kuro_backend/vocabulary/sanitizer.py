"""Vocabulary sanitization layer for user-facing responses."""

# --- Header Doc ---
# Purpose: Replace internal jargon with user-friendly vocabulary.
# Caller: langgraph_core.response_node.
# Dependencies: re, os.
# Main Functions: sanitize_response().
# Side Effects: None.

from __future__ import annotations

import os
import re

VOCAB_MAP: tuple[tuple[str, str], ...] = (
    (r"\bMem0\b", "memory system"),
    (r"\bChromaDB\b", "knowledge index"),
    (r"\bepisodic buffer\b", "conversation memory"),
    (r"\bruntime namespace\b", "context channel"),
)


def sanitize_response(text: str) -> str:
    if not text:
        return ""
    if os.getenv("KURO_DEV_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}:
        return text
    output = str(text)
    for pattern, replacement in VOCAB_MAP:
        output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)
    return output
