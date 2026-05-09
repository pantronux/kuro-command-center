from __future__ import annotations

from typing import Any, Dict, List


_PRINCIPLES = [
    "Never fabricate confidence.",
    "Preserve grounding over fluency.",
    "Prefer uncertainty over hallucination.",
    "Strategic consistency over conversational pleasing.",
    "User trust over response impressiveness.",
    "Governance integrity over response speed.",
]


def check_constitution(*, response_text: str) -> Dict[str, Any]:
    text = (response_text or "").lower()
    violations: List[str] = []
    if "100% guaranteed" in text:
        violations.append("Never fabricate confidence.")
    if "i made this up" in text:
        violations.append("Preserve grounding over fluency.")
    return {
        "principles": list(_PRINCIPLES),
        "violations": violations,
        "passed": len(violations) == 0,
    }
