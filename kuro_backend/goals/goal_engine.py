from __future__ import annotations

from typing import Any, Dict, List

from .goal_registry import build_default_goal_set
from .priority_resolver import resolve_priorities
from .utility_engine import UtilityProfile, compute_utility
from .decision_engine import decide


class GoalEngine:
    def run(self, *, user_input: str, confidence_score: float, contradiction_score: float) -> Dict[str, Any]:
        goals = [g.as_dict() for g in build_default_goal_set()]
        prioritized = resolve_priorities(goals, user_input)
        utility = compute_utility(
            UtilityProfile(),
            confidence_score=confidence_score,
            contradiction_score=contradiction_score,
        )
        decision = decide(prioritized, utility)
        top_priority = float(prioritized[0].get("resolved_priority", 0.0)) if prioritized else 0.0
        goal_block = "[GOAL_CONTEXT]\n" + "\n".join(
            f"- {g['goal_id']}: {g['title']} (priority={g['resolved_priority']:.2f})" for g in prioritized[:3]
        )
        return {
            "active_goals": prioritized,
            "goal_context_block": goal_block,
            "goal_priority_score": top_priority,
            "goal_decision_trace": decision.get("decision_trace", []),
            "goal_execution_plan": [],
        }


goal_engine = GoalEngine()
