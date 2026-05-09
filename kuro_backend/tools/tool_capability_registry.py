from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ToolCapability:
    tool_name: str
    requires_mutation: bool
    sensitivity: str
    category: str


_TOOL_CAPABILITIES: Dict[str, ToolCapability] = {
    "generate_excel_report": ToolCapability("generate_excel_report", True, "medium", "reporting"),
    "manage_files": ToolCapability("manage_files", True, "high", "filesystem"),
    "generate_report_template": ToolCapability("generate_report_template", True, "medium", "reporting"),
    "advanced_execution_tool": ToolCapability("advanced_execution_tool", True, "high", "execution"),
    "set_monthly_budget_tool": ToolCapability("set_monthly_budget_tool", True, "medium", "finance"),
    "get_budget_tool": ToolCapability("get_budget_tool", False, "low", "finance"),
    "add_recurring_expense_tool": ToolCapability("add_recurring_expense_tool", True, "medium", "finance"),
    "list_recurring_expenses_tool": ToolCapability("list_recurring_expenses_tool", False, "low", "finance"),
    "get_daily_api_cost_tool": ToolCapability("get_daily_api_cost_tool", False, "low", "finance"),
    "get_ticker_price_tool": ToolCapability("get_ticker_price_tool", False, "low", "market"),
    "get_market_news_tool": ToolCapability("get_market_news_tool", False, "low", "market"),
    "prediction_market_scan_tool": ToolCapability("prediction_market_scan_tool", False, "medium", "market"),
}


def get_tool_capability(tool_name: str) -> ToolCapability:
    return _TOOL_CAPABILITIES.get(
        tool_name,
        ToolCapability(tool_name=tool_name or "unknown", requires_mutation=True, sensitivity="high", category="unknown"),
    )


def list_tool_capabilities() -> Dict[str, ToolCapability]:
    return dict(_TOOL_CAPABILITIES)
