"""
Kuro AI — Cognitive Effort Allocator (T2 Metacognitive Tier)
=============================================================
Determines how much reasoning effort to expend on a given input.

Tomasello (2025): Rational agents allocate cognitive resources based on
task complexity (Computational Rationality). Trivial tasks → fast; tasks
touching dissertation Novelty → deep reasoning.

Effort Levels:
  "low"    → administrative / off-topic → minimal CoT injection
  "medium" → general research / tool tasks → standard CoT
  "high"   → dissertation novelty / methodology → extended CoT + multi-step

--- Header Doc ---
Purpose: Maps intent_category + input signals to an effort level string.
Caller: executive_monitor_node in langgraph_core.py.
Dependencies: re, stdlib only (no LLM call — must be fast).
Main Functions: compute(intent_category, user_input) -> Literal["low","medium","high"]
Side Effects: None.
"""
from __future__ import annotations

import re
from typing import Literal

EffortLevel = Literal["low", "medium", "high"]

# ── High-effort signals (dissertation novelty / methodology) ─────────────────
_HIGH_EFFORT_PATTERNS = re.compile(
    r"\b("
    r"novelty|kontribusi|contribution|originality|originalitas|"
    r"metodologi|methodology|kerangka|framework|research gap|"
    r"bab\s*[1-9]|chapter\s*[1-9]|hipotesis|hypothesis|"
    r"evidence|bukti|proposisi|proposition|"
    r"forensic|digital forensics?|ai forensic|"
    r"adversarial|poisoning|provenance|explainab|"
    r"disertasi|dissertation|phd|tesis|thesis|"
    r"eu ai act|uu pdp|iso\s*\d+|nist|gdpr|"
    r"teori|theory|konseptual|conceptual|"
    r"evaluasi|evaluation|validasi|validation|"
    r"kontradiksi|contradiction|counter.evidence"
    r")\b",
    re.IGNORECASE,
)

# ── Medium-effort signals (research / technical tasks) ───────────────────────
_MEDIUM_EFFORT_PATTERNS = re.compile(
    r"\b("
    r"analisis|analysis|analiz|analys|"
    r"implementasi|implementation|"
    r"debug|error|bug|fix|refactor|"
    r"kode|code|script|function|"
    r"audit|compliance|gap|risk|"
    r"referensi|reference|paper|artikel|article|"
    r"ringkas|summarize|summary|rangkum"
    r")\b",
    re.IGNORECASE,
)

# ── Low-effort bypass categories ─────────────────────────────────────────────
_LOW_EFFORT_CATEGORIES = {
    "off_track",
    "administrative",
    "greeting",
    "small_talk",
}


def compute(intent_category: str, user_input: str) -> EffortLevel:
    """
    Compute the cognitive effort level for a given input.

    Args:
        intent_category: String tag from attention_filter_node.
                         e.g. "dissertation", "research", "off_track", "administrative"
        user_input:      Raw user message text.

    Returns:
        "low" | "medium" | "high"
    """
    if intent_category in _LOW_EFFORT_CATEGORIES:
        return "low"

    text = user_input or ""
    if _HIGH_EFFORT_PATTERNS.search(text):
        return "high"
    if _MEDIUM_EFFORT_PATTERNS.search(text):
        return "medium"

    # Category-based fallback
    if intent_category in ("dissertation", "novelty"):
        return "high"
    if intent_category in ("research", "technical", "tool_action"):
        return "medium"

    return "low"


# ── Prompt Injection Helpers ─────────────────────────────────────────────────
_EFFORT_COT_INJECTIONS: dict[EffortLevel, str] = {
    "low": "",
    "medium": (
        "\n\n[COGNITIVE EFFORT: MEDIUM]\n"
        "Consider at least two perspectives before answering."
    ),
    "high": (
        "\n\n[COGNITIVE EFFORT: HIGH — DISSERTATION NOVELTY MODE]\n"
        "Perform deep reasoning:\n"
        "1. Identify hidden assumptions in this question.\n"
        "2. Look for potential gaps or counter-evidence.\n"
        "3. Consider the implications for the novelty contribution of the dissertation.\n"
        "4. If there are relevant joint commitments, reference them explicitly.\n"
        "5. Only then provide a structured and verified answer."
    ),
}


def get_cot_injection(effort: EffortLevel) -> str:
    """Return the CoT prompt injection string for this effort level."""
    return _EFFORT_COT_INJECTIONS.get(effort, "")
