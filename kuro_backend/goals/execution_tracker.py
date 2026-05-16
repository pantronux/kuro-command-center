from __future__ import annotations

from typing import Any, Dict, List


def summarize_execution_state(subgoals: List[Dict[str, Any]]) -> Dict[str, Any]:
    subgoals_list = subgoals or []
    total = len(subgoals_list)

    # ⚡ Bolt Optimization: Single-pass traversal
    # Replaced multiple O(n) generator expressions with one explicit loop.
    done = 0
    stalled = 0
    for s in subgoals_list:
        status = s.get("status")
        if status == "done":
            done += 1
        elif status == "stalled":
            stalled += 1

    return {
        "total": total,
        "done": done,
        "stalled": stalled,
        "completion_ratio": (done / total) if total else 0.0,
    }
