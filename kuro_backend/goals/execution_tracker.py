from __future__ import annotations

from typing import Any, Dict, List


def summarize_execution_state(subgoals: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(subgoals or [])
    done = sum(1 for s in subgoals or [] if s.get("status") == "done")
    stalled = sum(1 for s in subgoals or [] if s.get("status") == "stalled")
    return {
        "total": total,
        "done": done,
        "stalled": stalled,
        "completion_ratio": (done / total) if total else 0.0,
    }
