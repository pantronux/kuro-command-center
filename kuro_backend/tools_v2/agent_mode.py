"""Limited Agent Mode V2 planning loop."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def agent_max_steps() -> int:
    try:
        return max(1, min(int(os.getenv("KURO_AGENT_MAX_STEPS", "5")), 25))
    except Exception:
        return 5


class AgentModeRunner:
    def __init__(self, *, max_steps: Optional[int] = None) -> None:
        self.max_steps = max_steps if max_steps is not None else agent_max_steps()

    def run(
        self,
        *,
        goal: str,
        requested_steps: Optional[int] = None,
        allowed_tool_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        goal = str(goal or "").strip()
        requested = max(1, int(requested_steps or self.max_steps))
        step_count = min(requested, self.max_steps)
        allowed_tools = list(allowed_tool_ids or [])
        plan: List[Dict[str, Any]] = []
        for idx in range(step_count):
            plan.append(
                {
                    "step": idx + 1,
                    "action": self._step_action(idx, goal),
                    "tool_call": None,
                    "requires_policy": bool(allowed_tools),
                }
            )
        return {
            "goal": goal,
            "status": "planned",
            "max_steps": self.max_steps,
            "requested_steps": requested,
            "executed_steps": step_count,
            "max_steps_enforced": requested > self.max_steps,
            "allowed_tool_ids": allowed_tools,
            "plan": plan,
            "result": "Agent Mode V2 produced a bounded plan. Tool calls require ToolPolicy execution.",
        }

    def _step_action(self, index: int, goal: str) -> str:
        actions = [
            "Clarify objective and constraints",
            "Identify safe information sources",
            "Draft execution plan",
            "Review risks and approval needs",
            "Summarize next action",
        ]
        if index < len(actions):
            return actions[index]
        return f"Continue bounded work on: {goal[:80]}"
