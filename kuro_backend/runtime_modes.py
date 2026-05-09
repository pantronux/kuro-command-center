from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class RuntimeModeProfile:
    grounding_strictness: float
    tool_usage_strictness: float
    reasoning_depth: str
    creativity_allowance: float


_MODES: Dict[str, RuntimeModeProfile] = {
    "STRICT": RuntimeModeProfile(1.0, 1.0, "low", 0.1),
    "BALANCED": RuntimeModeProfile(0.8, 0.7, "medium", 0.4),
    "CREATIVE": RuntimeModeProfile(0.6, 0.5, "medium", 0.8),
    "RESEARCH": RuntimeModeProfile(0.9, 0.8, "high", 0.3),
    "ENTERPRISE": RuntimeModeProfile(1.0, 0.95, "medium", 0.2),
    "SAFE": RuntimeModeProfile(1.0, 1.0, "low", 0.05),
}


def resolve_runtime_mode(mode: str) -> Dict[str, object]:
    key = str(mode or "BALANCED").upper().strip()
    profile = _MODES.get(key, _MODES["BALANCED"])
    return {
        "runtime_mode": key if key in _MODES else "BALANCED",
        "profile": {
            "grounding_strictness": profile.grounding_strictness,
            "tool_usage_strictness": profile.tool_usage_strictness,
            "reasoning_depth": profile.reasoning_depth,
            "creativity_allowance": profile.creativity_allowance,
        },
    }
