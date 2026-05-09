from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .tool_capability_registry import get_tool_capability


@dataclass(frozen=True)
class ToolRiskProfile:
    execution_risk: float
    hallucination_risk: float
    privacy_risk: float
    governance_risk: float
    recursion_risk: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "execution_risk": self.execution_risk,
            "hallucination_risk": self.hallucination_risk,
            "privacy_risk": self.privacy_risk,
            "governance_risk": self.governance_risk,
            "recursion_risk": self.recursion_risk,
            "composite_risk": self.composite_risk(),
        }

    def composite_risk(self) -> float:
        return max(0.0, min(1.0, (self.execution_risk * 0.30) + (self.hallucination_risk * 0.20) + (self.privacy_risk * 0.20) + (self.governance_risk * 0.20) + (self.recursion_risk * 0.10)))


def score_tool_risk(tool_name: str, args: Dict[str, Any], user_input: str) -> ToolRiskProfile:
    cap = get_tool_capability(tool_name)
    text = f"{user_input or ''} {(args or {})}".lower()

    execution_risk = 0.70 if cap.requires_mutation else 0.20
    if any(k in text for k in ("delete", "rm -rf", "drop table", "truncate", "overwrite")):
        execution_risk = min(1.0, execution_risk + 0.25)

    privacy_risk = 0.65 if any(k in text for k in ("password", "token", "secret", "api key")) else (0.35 if cap.sensitivity == "high" else 0.15)
    governance_risk = 0.70 if cap.category in {"execution", "filesystem"} else 0.25
    recursion_risk = 0.65 if "loop" in text or "recursive" in text else 0.20
    hallucination_risk = 0.55 if "unknown" in text else 0.25

    return ToolRiskProfile(
        execution_risk=max(0.0, min(1.0, execution_risk)),
        hallucination_risk=max(0.0, min(1.0, hallucination_risk)),
        privacy_risk=max(0.0, min(1.0, privacy_risk)),
        governance_risk=max(0.0, min(1.0, governance_risk)),
        recursion_risk=max(0.0, min(1.0, recursion_risk)),
    )
