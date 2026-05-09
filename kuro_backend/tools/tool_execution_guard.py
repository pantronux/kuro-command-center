from __future__ import annotations

from typing import Any, Dict

from .tool_budget_manager import evaluate_tool_budget
from .tool_policy_engine import evaluate_tool_need
from .tool_risk_scoring import score_tool_risk


def evaluate_tool_execution_guard(
    *,
    user_input: str,
    next_step: str,
    tool_name: str,
    tool_args: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    need = evaluate_tool_need(user_input=user_input, next_step=next_step, tool_name=tool_name)
    if need["status"] == "tool_not_required":
        return {
            "decision": "tool_not_required",
            "reason": need.get("reason", "unknown"),
            "tool_governance_status": need,
            "tool_risk_profile": {},
            "tool_budget_status": state.get("tool_budget_status", {}),
        }

    risk = score_tool_risk(tool_name, tool_args or {}, user_input)
    risk_payload = risk.as_dict()
    budget = evaluate_tool_budget(state=state)

    if not budget.get("allowed", False):
        return {
            "decision": "tool_blocked",
            "reason": "tool_budget_exhausted",
            "tool_governance_status": {"status": "blocked", "policy": "budget"},
            "tool_risk_profile": risk_payload,
            "tool_budget_status": budget,
        }

    if float(risk_payload.get("composite_risk", 0.0)) >= 0.75:
        return {
            "decision": "tool_blocked",
            "reason": "risk_too_high",
            "tool_governance_status": {"status": "blocked", "policy": "risk"},
            "tool_risk_profile": risk_payload,
            "tool_budget_status": budget,
        }

    return {
        "decision": "tool_allowed",
        "reason": "passed",
        "tool_governance_status": {"status": "allowed", "policy": "standard"},
        "tool_risk_profile": risk_payload,
        "tool_budget_status": budget,
    }
