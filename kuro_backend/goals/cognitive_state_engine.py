from __future__ import annotations

from typing import Any, Dict


def build_cognitive_state(*, goal_priority_score: float, confidence_score: float, contradiction_score: float, user_input: str) -> Dict[str, Any]:
    depth = min(1.0, max(0.1, len((user_input or "")) / 1200.0))
    return {
        "strategic_focus": goal_priority_score,
        "uncertainty_pressure": max(0.0, min(1.0, 1.0 - confidence_score)),
        "cognitive_load": depth,
        "topic_persistence": min(1.0, 0.45 + goal_priority_score * 0.4),
        "confidence_stability": max(0.0, min(1.0, confidence_score - contradiction_score * 0.5)),
    }


cognitive_state_engine = type("CognitiveStateEngine", (), {"build": staticmethod(build_cognitive_state)})()
