from __future__ import annotations

from typing import Dict

from .cognition_roles import ROLE_GEMINI_PRIMARY, ROLE_OPENAI_MODEL


def select_role(*, contradiction_score: float, confidence_score: float) -> str:
    # High contradiction / low confidence -> request validation role.
    if contradiction_score >= 0.45 or confidence_score <= 0.55:
        return ROLE_OPENAI_MODEL
    return ROLE_GEMINI_PRIMARY


def build_router_note(role: str) -> str:
    return f"[COGNITIVE_ROUTER_DECISION] selected_role={role}"
