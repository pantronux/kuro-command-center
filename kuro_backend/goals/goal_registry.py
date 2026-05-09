from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List


@dataclass
class GoalRecord:
    goal_id: str
    title: str
    priority: float
    status: str = "active"
    source: str = "runtime"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_default_goal_set() -> List[GoalRecord]:
    return [
        GoalRecord("dissertation_continuity", "Preserve dissertation continuity", 0.92, source="system"),
        GoalRecord("grounded_answering", "Maintain grounded answer quality", 0.95, source="system"),
        GoalRecord("safe_execution", "Prevent unsafe execution paths", 0.97, source="system"),
    ]
