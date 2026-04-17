"""Kuro AI V5.5 — Per-section token budget enforcement for LLM context assembly.

Prevents context window overflow (which causes latency spikes and
hallucinations) by trimming each injected block to a fixed quota before
concatenation. Token counting is approximated via a char/token ratio that
matches Gemini's Indonesian tokenization observed in production (~3.8 chars
per token).

Design notes:
- Zero external deps; works entirely on strings.
- Section-aware quotas so high-signal blocks (memory, compliance) win over
  lower-signal ones (tool results).
- Trimming preserves head + tail of the block so important framing sentences
  are not lost (helpful for RAG passages and summaries).
- `KURO_MAX_CONTEXT_TOKENS` env var is a hard ceiling across the whole
  assembled prompt and acts as a final safety net.
"""
from __future__ import annotations

import logging
import os
from typing import Final, Iterable, Mapping

logger = logging.getLogger(__name__)

# Approximate chars-per-token for Gemini on Indonesian/English mixed text.
# Tuned slightly conservative so we under-estimate tokens (= trim more).
_CHARS_PER_TOKEN: Final[float] = 3.8

# Hard global ceiling. Can be overridden by env.
MAX_CONTEXT_TOKENS: Final[int] = int(os.getenv("KURO_MAX_CONTEXT_TOKENS", "6000"))

# Per-section default quotas (in approximate tokens). Order matters for
# priority-based fallback trimming when over the global ceiling.
SECTION_QUOTAS: Final[Mapping[str, int]] = {
    "memory_injection": 1800,
    "mem0":             900,
    "compliance":       1500,
    "habit":            800,
    "tool_result":      600,
    "referent":         300,
    "summary":          600,
    # catch-all bucket for ad-hoc blocks not matching the above
    "other":            500,
}

# Sections sorted from least-important (first to trim) to most-important.
_TRIM_PRIORITY: Final[tuple[str, ...]] = (
    "referent",
    "tool_result",
    "habit",
    "mem0",
    "summary",
    "compliance",
    "memory_injection",
    "other",
)


def approx_tokens(text: str | None) -> int:
    """Approximate token count for a string using char/token heuristic."""
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def tokens_to_chars(tokens: int) -> int:
    """Inverse of approx_tokens for clamping purposes."""
    return max(1, int(tokens * _CHARS_PER_TOKEN))


def trim_section(section: str, text: str, *, quota_override: int | None = None) -> str:
    """Trim a single section to its per-section quota.

    Strategy: keep head and tail, ellipsize the middle. That way framing
    sentences (the injected section headers and concluding rules) remain
    intact — critical for compliance/habit blocks.
    """
    if not text:
        return ""
    quota = quota_override if quota_override is not None else SECTION_QUOTAS.get(section, SECTION_QUOTAS["other"])
    max_chars = tokens_to_chars(quota)
    if len(text) <= max_chars:
        return text
    head_chars = int(max_chars * 0.7)
    tail_chars = max_chars - head_chars - len(_ELIPSIS)
    if tail_chars <= 0:
        return text[:max_chars]
    trimmed = text[:head_chars] + _ELIPSIS + text[-tail_chars:]
    logger.debug(
        "[TOKEN_BUDGET] section=%s trimmed %d->%d chars (quota=%d tok)",
        section, len(text), len(trimmed), quota,
    )
    return trimmed


def apply_section_budget(sections: Mapping[str, str]) -> dict[str, str]:
    """Trim every section to its quota, returning a new dict.

    Unknown section names fall back to the ``other`` bucket.
    """
    return {name: trim_section(name, (text or "")) for name, text in sections.items()}


def enforce_global_ceiling(ordered_parts: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Enforce the global context ceiling by trimming lowest-priority sections first.

    ``ordered_parts`` is the final assembly order (name, text). The returned list
    preserves the same order so downstream concatenation is stable.
    """
    parts: list[tuple[str, str]] = [(n, t) for n, t in ordered_parts if t]
    total = sum(approx_tokens(t) for _, t in parts)
    if total <= MAX_CONTEXT_TOKENS:
        return parts

    overshoot = total - MAX_CONTEXT_TOKENS
    logger.info(
        "[TOKEN_BUDGET] global overshoot by %d tokens (total=%d, cap=%d); trimming low-priority sections",
        overshoot, total, MAX_CONTEXT_TOKENS,
    )

    index: dict[str, list[int]] = {}
    for idx, (name, _text) in enumerate(parts):
        index.setdefault(name, []).append(idx)

    for section_name in _TRIM_PRIORITY:
        if overshoot <= 0:
            break
        for idx in index.get(section_name, []):
            if overshoot <= 0:
                break
            name, text = parts[idx]
            cur_tokens = approx_tokens(text)
            # Minimum floor: never drop a section below 80 tokens (~320 chars)
            floor_tokens = min(80, cur_tokens)
            target = max(floor_tokens, cur_tokens - overshoot)
            trimmed = trim_section(name, text, quota_override=target)
            parts[idx] = (name, trimmed)
            overshoot -= cur_tokens - approx_tokens(trimmed)

    return parts


_ELIPSIS: Final[str] = "\n\n[...truncated for token budget...]\n\n"


# ---------------------------------------------------------------------------
# P2.4 — Duplicate block collapse
# ---------------------------------------------------------------------------
# Multiple injection pipelines (short-term, RAG, referent grounding) can all
# carry the same fact through slightly different formatting. We SHA1 every
# ~200-char window of each section and drop sections whose content mostly
# overlaps with an earlier section in the same assembly.

import hashlib as _hashlib

_DUP_WINDOW_CHARS: Final[int] = 200
_DUP_OVERLAP_THRESHOLD: Final[float] = 0.6


def _rolling_hashes(text: str, *, window: int = _DUP_WINDOW_CHARS) -> set[str]:
    if not text:
        return set()
    hashes: set[str] = set()
    for start in range(0, max(1, len(text) - window + 1), max(1, window // 2)):
        chunk = text[start:start + window]
        if len(chunk) < window // 2:
            break
        hashes.add(_hashlib.sha1(chunk.encode("utf-8", errors="replace")).hexdigest()[:16])
    return hashes


def collapse_duplicate_blocks(parts: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop later parts that overlap heavily with earlier ones in the sequence.

    Returns a new list preserving order. Useful to avoid injecting the same
    recent_messages content twice (once as short-term summary and once as a
    verbatim block).
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for name, text in parts:
        if not text:
            continue
        h = _rolling_hashes(text)
        if not h:
            out.append((name, text))
            continue
        overlap = len(h & seen) / max(1, len(h))
        if overlap >= _DUP_OVERLAP_THRESHOLD and seen:
            logger.debug(
                "[TOKEN_BUDGET] collapsing duplicate section=%s overlap=%.2f",
                name, overlap,
            )
            continue
        seen |= h
        out.append((name, text))
    return out


__all__ = [
    "MAX_CONTEXT_TOKENS",
    "SECTION_QUOTAS",
    "apply_section_budget",
    "approx_tokens",
    "collapse_duplicate_blocks",
    "enforce_global_ceiling",
    "tokens_to_chars",
    "trim_section",
]
