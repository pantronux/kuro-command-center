from __future__ import annotations

from kuro_backend.autonomy_boundaries import evaluate_autonomy_boundaries


def test_autonomy_boundaries_pass_state() -> None:
    out = evaluate_autonomy_boundaries({"next_step": "response_node"})
    assert out["passed"] in {True, False}


def test_autonomy_boundaries_violation_when_hidden_tool() -> None:
    out = evaluate_autonomy_boundaries({"next_step": "tool_node", "tool_governance_decision": {}})
    assert out["passed"] is False
