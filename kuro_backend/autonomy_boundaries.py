from __future__ import annotations

from typing import Any, Dict


RULES = [
    "No hidden tool execution.",
    "No unrestricted memory mutation.",
    "No autonomous self-modification.",
    "No silent governance changes.",
    "No recursive planning without budget approval.",
]


def evaluate_autonomy_boundaries(state: Dict[str, Any]) -> Dict[str, Any]:
    violations = []
    if state.get("next_step") == "tool_node" and not state.get("tool_governance_decision"):
        violations.append("No hidden tool execution.")
    if int(state.get("retrieval_retry_count", 0) or 0) > 8:
        violations.append("No recursive planning without budget approval.")
    return {
        "rules": list(RULES),
        "violations": violations,
        "passed": len(violations) == 0,
    }
