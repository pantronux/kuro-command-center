from __future__ import annotations

from typing import Any, Dict, List


def decide(prioritized_goals: List[Dict[str, Any]], utility: Dict[str, float]) -> Dict[str, Any]:
    primary = prioritized_goals[0] if prioritized_goals else {"goal_id": "none", "title": "No active goals"}
    return {
        "primary_goal": primary,
        "strategic_score": float(utility.get("strategic_score", 0.0)),
        "decision_trace": [
            f"primary_goal={primary.get('goal_id', 'none')}",
            f"strategic_score={utility.get('strategic_score', 0.0):.3f}",
            f"risk_penalty={utility.get('risk_penalty', 0.0):.3f}",
        ],
    }
