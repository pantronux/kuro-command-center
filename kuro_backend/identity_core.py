from __future__ import annotations

from typing import Any, Dict


IDENTITY_ANCHORS = {
    "grounding_first": True,
    "uncertainty_honesty": True,
    "strategic_reasoning": True,
    "governance_alignment": True,
    "anti_hallucination_priority": True,
}


def evaluate_identity_alignment(text: str) -> Dict[str, Any]:
    content = (text or "").lower()
    drift_detected = "fabricated" in content
    return {
        "anchors": dict(IDENTITY_ANCHORS),
        "drift_detected": drift_detected,
        "identity_score": 0.25 if drift_detected else 0.95,
    }
