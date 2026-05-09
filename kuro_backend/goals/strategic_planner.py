from __future__ import annotations

from typing import Any, Dict, List

from .subgoal_graph import build_subgoal_graph
from .execution_tracker import summarize_execution_state


class StrategicPlanner:
    def plan(self, user_input: str) -> Dict[str, Any]:
        subgoals = build_subgoal_graph(user_input)
        state = summarize_execution_state(subgoals)
        return {
            "subgoals": subgoals,
            "execution_state": state,
            "next_focus": subgoals[0]["subgoal_id"] if subgoals else "none",
        }


strategic_planner = StrategicPlanner()
