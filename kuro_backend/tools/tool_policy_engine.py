from __future__ import annotations

from typing import Any, Dict


def evaluate_tool_need(*, user_input: str, next_step: str, tool_name: str) -> Dict[str, Any]:
    text = (user_input or "").lower()
    if next_step != "tool_node":
        return {"status": "tool_not_required", "reason": "router_not_requesting_tool"}

    if not tool_name:
        return {"status": "tool_allowed", "reason": "deferred_tool_resolution"}

    chat_only_markers = ("explain", "jelaskan", "ringkas", "summarize", "opini", "concept")
    if any(m in text for m in chat_only_markers) and tool_name in {
        "generate_excel_report",
        "manage_files",
        "advanced_execution_tool",
    }:
        return {"status": "tool_not_required", "reason": "reasoning_sufficient"}

    return {"status": "tool_allowed", "reason": "tool_required_by_router"}
