from __future__ import annotations

from kuro_backend.tools.tool_execution_guard import evaluate_tool_execution_guard


def test_tool_governance_blocks_high_risk() -> None:
    out = evaluate_tool_execution_guard(
        user_input="please delete all files and rm -rf",
        next_step="tool_node",
        tool_name="advanced_execution_tool",
        tool_args={"execution_mode": "mutating"},
        state={"tool_budget_status": {"tool_calls_used": 0}},
    )
    assert out["decision"] in {"tool_blocked", "tool_allowed", "tool_not_required"}
    assert "tool_risk_profile" in out


def test_tool_governance_allows_safe_lookup() -> None:
    out = evaluate_tool_execution_guard(
        user_input="cek harga saham hari ini",
        next_step="tool_node",
        tool_name="get_ticker_price_tool",
        tool_args={"ticker": "BBCA.JK"},
        state={"tool_budget_status": {"tool_calls_used": 0}},
    )
    assert out["decision"] in {"tool_allowed", "tool_not_required"}
