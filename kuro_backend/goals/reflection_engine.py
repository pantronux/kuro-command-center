from __future__ import annotations

from typing import Any, Dict


def reflect_on_outcome(goal_priority_score: float, confidence_score: float, contradiction_score: float) -> Dict[str, Any]:
    quality = max(0.0, min(1.0, (goal_priority_score * 0.35) + (confidence_score * 0.45) - (contradiction_score * 0.30)))
    return {
        "decision_quality": quality,
        "drift_detected": contradiction_score >= 0.45,
        "recommendation": "reprioritize" if contradiction_score >= 0.45 else "continue",
    }
