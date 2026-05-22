"""Runtime package entrypoint for V2 runtime registry and context."""
from __future__ import annotations

from kuro_backend.runtime.boundary_guard import (
    BoundaryViolationError,
    assert_memory_access,
    assert_prompt_access,
    assert_tool_access,
)
from kuro_backend.runtime.runtime_context import RuntimeContext, resolve_runtime_context
from kuro_backend.runtime.runtime_loader import get_runtime_config, load_runtime_configs
from kuro_backend.runtime.runtime_registry import RuntimeConfig, RuntimeRegistry


__all__ = [
    "BoundaryViolationError",
    "RuntimeConfig",
    "RuntimeContext",
    "RuntimeRegistry",
    "assert_memory_access",
    "assert_prompt_access",
    "assert_tool_access",
    "get_runtime_config",
    "load_runtime_configs",
    "resolve_runtime_context",
]
