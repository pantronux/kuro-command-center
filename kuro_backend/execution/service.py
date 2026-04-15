"""
Execution service boundary for OpenClaw delegation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def execute_openclaw_skill_sync(skill_name: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Synchronous facade used by tool layer.
    Keeps OpenClaw bridge wiring outside caller modules.
    """
    from kuro_backend.execution.openclaw_bridge import execute_openclaw_skill
    from kuro_backend.tools.base_tools import _run_async_coro_sync

    return _run_async_coro_sync(
        execute_openclaw_skill(skill_name=skill_name, params=payload or {})
    )

