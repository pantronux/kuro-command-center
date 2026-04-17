"""
Kuro AI V5.5 — Execution service boundary for OpenClaw delegation.

The tool layer calls this synchronously (e.g. from `advanced_execution_tool`
running in a LangGraph worker thread). We route to the pure-blocking variant
of the bridge so we do NOT spin up nested event loops.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def execute_openclaw_skill_sync(
    skill_name: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Synchronous facade used by tool layer.

    Keeps OpenClaw bridge wiring outside caller modules.
    """
    from kuro_backend.execution.openclaw_bridge import execute_openclaw_skill_blocking

    return execute_openclaw_skill_blocking(skill_name=skill_name, params=payload or {})
