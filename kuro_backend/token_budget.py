"""Kuro AI V6.0 Sovereign — Per-section token budget enforcement for LLM context assembly.

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

--- Header Doc ---
Purpose: Per-section token budgeting + trim policy for assembled LLM prompts.
Caller: memory_coordinator.build_context_for_llm, langgraph_core response_node.
Dependencies: stdlib only (logging, os).
Main Functions: SECTION_QUOTAS, build_budgeted_context(), approximate_tokens(), trim_to_tokens().
Side Effects: None (pure string functions + logging).
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
    "mem0":             700,
    "tool_result":      600,
    "referent":         700,
    "finance":          450,
    "market":           350,
    "playground_advisor": 900,
    # catch-all bucket for ad-hoc blocks not matching the above
    "other":            500,
}

# Sections sorted from least-important (first to trim) to most-important.
# Layer 3 (habit, compliance, ssot_factual) are placed LAST so SSoT data is
# the final candidate for trimming — see Persona-Aware Context Management
# (V5.5) L3 immutability contract.
_TRIM_PRIORITY: Final[tuple[str, ...]] = (
    "tool_result",
    "playground_advisor",
    "mem0",
    "finance",
    "market",
    "memory_injection",
    "referent",
    "other",
    "ssot_factual",
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


# ---------------------------------------------------------------------------
# Persona-Aware Budgets (V5.5)
# ---------------------------------------------------------------------------
# Every persona in :mod:`kuro_backend.personas` owns a :class:`ContextBudget`
# with Layer 1 / Layer 2 / Layer 3 weights. The helpers below derive
# per-section quotas from those weights so the same ``apply_section_budget``
# contract can be used dynamically instead of the static table above.
#
# Layer mapping (must stay in sync with memory_coordinator):
#   Layer 1 (recent)   -> memory_injection (raw recent turns)
#   Layer 2 (semantic) -> mem0, referent
#   Layer 3 (factual)  -> ssot_factual
#   Other tool metadata falls through to ``tool_result`` / ``other``.

_LAYER1_SECTIONS: Final[tuple[str, ...]] = ("memory_injection",)
_LAYER2_SECTIONS: Final[tuple[str, ...]] = ("mem0", "referent")
_LAYER3_SECTIONS: Final[tuple[str, ...]] = ("ssot_factual",)
_FIXED_SECTIONS: Final[Mapping[str, int]] = {
    # Non-layer buckets keep small, fixed quotas independent of persona.
    "tool_result": 600,
    "playground_advisor": 900,
    "other":       500,
}

# Within each layer, split the total layer quota across its sections.
_LAYER2_SPLIT: Final[Mapping[str, float]] = {
    "mem0":             0.35,
    "referent":         0.65,
}
_LAYER3_SPLIT: Final[Mapping[str, float]] = {
    "ssot_factual": 1.0,
}


def build_persona_section_quotas(budget) -> dict[str, int]:
    """Derive per-section token quotas from a :class:`ContextBudget`.

    Returns a dict covering every known section plus the fixed non-layer
    buckets. Unknown sections fall back to the ``other`` entry.
    """
    quotas: dict[str, int] = {}
    layer1 = max(1, budget.layer1_tokens)
    layer2 = max(1, budget.layer2_tokens)
    layer3 = max(1, budget.layer3_tokens)

    for name in _LAYER1_SECTIONS:
        quotas[name] = layer1
    for name in _LAYER2_SECTIONS:
        quotas[name] = max(80, int(layer2 * _LAYER2_SPLIT[name]))
    for name in _LAYER3_SECTIONS:
        quotas[name] = max(80, int(layer3 * _LAYER3_SPLIT[name]))
    for name, qty in _FIXED_SECTIONS.items():
        quotas[name] = qty
    return quotas


def apply_persona_budget(
    sections: Mapping[str, str], budget
) -> dict[str, str]:
    """Persona-aware variant of :func:`apply_section_budget`.

    Uses :func:`build_persona_section_quotas` to size each section according
    to the persona's LayerWeights.
    """
    quotas = build_persona_section_quotas(budget)
    return {
        name: trim_section(name, (text or ""), quota_override=quotas.get(name))
        for name, text in sections.items()
    }


def enforce_global_ceiling(
    ordered_parts: Iterable[tuple[str, str]],
    *,
    budget=None,
) -> list[tuple[str, str]]:
    """Enforce the global context ceiling by trimming lowest-priority sections first.

    ``ordered_parts`` is the final assembly order (name, text). The returned list
    preserves the same order so downstream concatenation is stable.

    When ``budget`` (a ``ContextBudget``) is given, uses its ``total_tokens``
    and protects Layer 3 sections (habit / compliance / ssot_factual) with a
    hard floor of ``budget.layer3_floor_tokens``. Otherwise falls back to the
    module-level :data:`MAX_CONTEXT_TOKENS`.
    """
    parts: list[tuple[str, str]] = [(n, t) for n, t in ordered_parts if t]
    cap = getattr(budget, "total_tokens", None) or MAX_CONTEXT_TOKENS
    total = 0
    for _, t in parts:
        total += approx_tokens(t)
    if total <= cap:
        return parts

    overshoot = total - cap
    logger.info(
        "[TOKEN_BUDGET] global overshoot by %d tokens (total=%d, cap=%d); trimming low-priority sections",
        overshoot, total, cap,
    )

    index: dict[str, list[int]] = {}
    for idx, (name, _text) in enumerate(parts):
        index.setdefault(name, []).append(idx)

    layer3_floor_tokens: int | None = None
    if budget is not None:
        layer3_floor_tokens = getattr(budget, "layer3_floor_tokens", None)

    for section_name in _TRIM_PRIORITY:
        if overshoot <= 0:
            break
        # SSoT / Layer 3 sections must NEVER be touched until every other
        # section is already at its floor — see memory_coordinator Layer 3
        # immutability contract.
        is_layer3 = section_name in _LAYER3_SECTIONS
        for idx in index.get(section_name, []):
            if overshoot <= 0:
                break
            name, text = parts[idx]
            cur_tokens = approx_tokens(text)
            if is_layer3 and layer3_floor_tokens is not None:
                # Protect: never drop any Layer 3 section below its share of the
                # persona floor (per-section floor = layer3_floor / 3 sections).
                per_section_floor = max(80, int(layer3_floor_tokens / max(1, len(_LAYER3_SECTIONS))))
                floor_tokens = min(cur_tokens, per_section_floor)
            else:
                floor_tokens = min(80, cur_tokens)
            target = max(floor_tokens, cur_tokens - overshoot)
            trimmed = trim_section(name, text, quota_override=target)
            parts[idx] = (name, trimmed)
            overshoot -= cur_tokens - approx_tokens(trimmed)

    if overshoot > 0:
        logger.warning(
            "[TOKEN_BUDGET] global cap still exceeded by %d tokens after trimming "
            "(Layer 3 SSoT floor protected; allowing overshoot rather than evicting SSoT)",
            overshoot,
        )

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
    """Drop later parts that overlap heavily with earlier ones in the sequence."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for name, text in reversed(list(parts)):
        if not text:
            continue
        lines = text.split("\n")
        body_text = "\n".join(lines[1:]) if len(lines) > 1 and lines[0].startswith("[") and lines[0].endswith("]") else text
        body_text = body_text.strip()
        h = _rolling_hashes(body_text)
        if not h:
            if len(body_text) > 0:
                h = {body_text}
            else:
                out.insert(0, (name, text))
                continue
        overlap = len(h & seen) / max(1, len(h)) if len(h) > 0 else 0
        if overlap >= _DUP_OVERLAP_THRESHOLD and seen:
            logger.info("[TOKEN_BUDGET] collapsing duplicate section=%s overlap=%.2f", name, overlap)
            continue
        seen |= h
        out.insert(0, (name, text))
    return out


__all__ = [
    "MAX_CONTEXT_TOKENS",
    "SECTION_QUOTAS",
    "apply_persona_budget",
    "apply_section_budget",
    "approx_tokens",
    "build_persona_section_quotas",
    "collapse_duplicate_blocks",
    "enforce_global_ceiling",
    "tokens_to_chars",
    "trim_section",
]
