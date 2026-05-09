from __future__ import annotations

from .response_sanitizer import response_sanitizer


def detect_policy_leakage(text: str) -> bool:
    if not text:
        return False
    verdict = response_sanitizer.validate_user_safe_output(text)
    return verdict.blocked


def block_internal_metadata(text: str) -> str:
    if not text:
        return ""
    if detect_policy_leakage(text):
        return ""
    return text


def sanitize_stream_chunk(text: str) -> str:
    """Per-chunk sanitization for SSE/token streaming safety."""
    if not text:
        return ""
    clean = response_sanitizer.strip_internal_labels(text)
    clean = response_sanitizer.sanitize_chain_of_thought(clean)
    clean = block_internal_metadata(clean)
    return clean
