"""
Runtime boundary guard for cognitive isolation checks.
"""

# --- Header Doc ---
# Purpose: Enforces cognitive isolation between runtimes.
#          Default (KURO_V2_STRICT_MODE=false): logs violations, never blocks.
#          Strict (KURO_V2_STRICT_MODE=true): raises BoundaryViolationError.
# Caller: memory_coordinator.py, langgraph_core.py tool dispatch
# Dependencies: runtime_context.py, intelligence_db.py
# Main Functions: assert_memory_access, assert_tool_access, assert_prompt_access
# Side Effects: Writes structured record to boundary_violations table on violation

from __future__ import annotations

import logging
import os

from kuro_backend.runtime.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)

SHARED_NAMESPACES = frozenset(["kuro.shared", "kuro.global_knowledge"])


class BoundaryViolationError(PermissionError):
    pass


def _is_strict() -> bool:
    return os.getenv("KURO_V2_STRICT_MODE", "false").lower() == "true"


def _record_violation(
    runtime_id: str,
    username: str,
    resource_type: str,
    resource_id: str,
    reason: str,
    trace_id: str = "",
) -> None:
    """Log structured boundary violation to DB and logger. Never raises."""
    msg = (
        f"BOUNDARY | runtime={runtime_id} user={username} "
        f"{resource_type}={resource_id!r} reason={reason} trace={trace_id}"
    )
    logger.warning(msg)
    try:
        from kuro_backend import intelligence_db

        intelligence_db.log_boundary_violation(
            runtime_id=runtime_id,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
            strict_mode=_is_strict(),
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("Failed to persist boundary violation to DB: %s", exc)


def assert_memory_access(ctx: RuntimeContext, namespace: str) -> None:
    allowed = {ctx.config.memory_namespace} | SHARED_NAMESPACES
    if namespace not in allowed:
        _record_violation(
            ctx.runtime_id,
            ctx.username,
            "memory_namespace",
            namespace,
            f"not in allowed={sorted(allowed)}",
            trace_id=ctx.trace_id,
        )
        if _is_strict():
            raise BoundaryViolationError(
                f"Runtime {ctx.runtime_id!r} cannot access namespace {namespace!r}"
            )


def assert_tool_access(ctx: RuntimeContext, tool_name: str) -> None:
    if tool_name not in ctx.config.tools:
        _record_violation(
            ctx.runtime_id,
            ctx.username,
            "tool",
            tool_name,
            f"not in allowed_tools={ctx.config.tools}",
            trace_id=ctx.trace_id,
        )
        if _is_strict():
            raise BoundaryViolationError(
                f"Runtime {ctx.runtime_id!r} cannot use tool {tool_name!r}"
            )


def assert_prompt_access(ctx: RuntimeContext, prompt_id: str) -> None:
    if prompt_id not in ctx.config.prompt_stack:
        _record_violation(
            ctx.runtime_id,
            ctx.username,
            "prompt",
            prompt_id,
            f"not in prompt_stack={ctx.config.prompt_stack}",
            trace_id=ctx.trace_id,
        )
        if _is_strict():
            raise BoundaryViolationError(
                f"Runtime {ctx.runtime_id!r} cannot use prompt {prompt_id!r}"
            )
