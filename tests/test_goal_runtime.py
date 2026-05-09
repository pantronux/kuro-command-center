from __future__ import annotations

from kuro_backend.goals.goal_engine import goal_engine
from kuro_backend.goals.strategic_planner import strategic_planner
from kuro_backend.goals.progress_evaluator import evaluate_progress


def test_goal_runtime_generates_prioritized_goals() -> None:
    result = goal_engine.run(
        user_input="susun prioritas disertasi dan evidence plan",
        confidence_score=0.82,
        contradiction_score=0.10,
    )
    assert isinstance(result.get("active_goals"), list)
    assert result.get("active_goals")
    assert isinstance(result.get("goal_context_block"), str)
    assert "[GOAL_CONTEXT]" in result.get("goal_context_block", "")
    assert float(result.get("goal_priority_score", 0.0)) >= 0.0
    assert isinstance(result.get("goal_decision_trace"), list)


def test_strategic_planning_and_progress() -> None:
    plan = strategic_planner.plan("buat rencana eksekusi per bab disertasi")
    assert isinstance(plan.get("subgoals"), list)
    assert len(plan.get("subgoals", [])) >= 1
    progress = evaluate_progress(plan.get("execution_state", {}))
    assert "completion_ratio" in progress
    assert 0.0 <= float(progress["completion_ratio"]) <= 1.0
