from __future__ import annotations

from typing import Any, Dict


def compute_grounding_score(state: Dict[str, Any]) -> Dict[str, float]:
    confidence = float(state.get("confidence_score", 0.0) or 0.0)
    contradiction = float(state.get("contradiction_score", 0.0) or 0.0)
    score = max(0.0, min(1.0, confidence - (contradiction * 0.4)))
    return {"grounding_score": score}
