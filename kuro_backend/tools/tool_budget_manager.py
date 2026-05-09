from __future__ import annotations

import os
from typing import Any, Dict


_MAX_TOOL_CALLS = int(os.getenv("KURO_CANVAS3_MAX_TOOL_CALLS", "4"))


def evaluate_tool_budget(*, state: Dict[str, Any]) -> Dict[str, Any]:
    status = state.get("tool_budget_status") if isinstance(state.get("tool_budget_status"), dict) else {}
    used = int(status.get("tool_calls_used", 0) or 0)
    remaining = _MAX_TOOL_CALLS - used
    allowed = remaining > 0
    return {
        "tool_calls_used": used,
        "max_tool_calls": _MAX_TOOL_CALLS,
        "remaining_tool_calls": max(0, remaining),
        "allowed": allowed,
        "decision": "allow" if allowed else "block",
    }


def consume_tool_budget(status: Dict[str, Any]) -> Dict[str, Any]:
    used = int((status or {}).get("tool_calls_used", 0) or 0) + 1
    remaining = _MAX_TOOL_CALLS - used
    return {
        "tool_calls_used": used,
        "max_tool_calls": _MAX_TOOL_CALLS,
        "remaining_tool_calls": max(0, remaining),
        "allowed": remaining >= 0,
        "decision": "allow" if remaining >= 0 else "block",
    }
