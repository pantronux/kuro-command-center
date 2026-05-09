from __future__ import annotations

from typing import Any, Dict

from .ai_risk_classifier import classify_risk


def evaluate_policy(user_input: str, *, contradiction_score: float, confidence_score: float) -> Dict[str, Any]:
    risk = classify_risk(user_input, contradiction_score, confidence_score)
    action = "allow"
    if risk["total_risk"] >= 0.65:
        action = "downgrade"
    if risk["unsafe_execution_risk"] >= 0.7:
        action = "restrict_tools"
    return {
        "status": "ok",
        "action": action,
        "risk": risk,
    }
