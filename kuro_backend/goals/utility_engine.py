from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class UtilityProfile:
    hallucination_avoidance: float = 0.99
    security_integrity: float = 0.95
    research_accuracy: float = 0.96
    strategic_consistency: float = 0.91
    entertainment_value: float = 0.25


def compute_utility(profile: UtilityProfile, *, confidence_score: float, contradiction_score: float) -> Dict[str, float]:
    strategic_score = (
        (confidence_score * 0.45)
        + (profile.strategic_consistency * 0.25)
        + (profile.research_accuracy * 0.20)
        + (profile.security_integrity * 0.10)
        - (contradiction_score * 0.35)
    )
    return {
        "strategic_score": max(0.0, min(1.0, strategic_score)),
        "risk_penalty": max(0.0, min(1.0, contradiction_score)),
    }
