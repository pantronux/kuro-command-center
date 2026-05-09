from __future__ import annotations

from typing import Any, Dict, List


def build_subgoal_graph(user_input: str) -> List[Dict[str, Any]]:
    lowered = (user_input or "").lower()
    if any(k in lowered for k in ("disertasi", "dissertation", "paper", "research")):
        return [
            {"subgoal_id": "literature_mapping", "title": "Literature mapping", "status": "pending"},
            {"subgoal_id": "gap_validation", "title": "Gap validation", "status": "pending"},
            {"subgoal_id": "experiment_planning", "title": "Experiment planning", "status": "pending"},
            {"subgoal_id": "benchmark_evaluation", "title": "Benchmark evaluation", "status": "pending"},
        ]
    return [{"subgoal_id": "context_clarification", "title": "Context clarification", "status": "pending"}]
