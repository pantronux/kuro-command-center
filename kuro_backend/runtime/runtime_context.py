"""
Runtime context resolver for request-scoped runtime data.
"""

# --- Header Doc ---
# Purpose: Request-scoped runtime context. Resolves runtime_id to config.
#          IMPORTANT: RuntimeContext objects must NEVER be stored in LangGraph state.
#          LangGraph state carries only: runtime_id (str), runtime_namespace (str).
# Caller: main.py FastAPI routes, langgraph_core.py node functions
# Dependencies: runtime_registry.py
# Main Functions: resolve_runtime_context(), RuntimeContext

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from kuro_backend.runtime.runtime_registry import RuntimeConfig, RuntimeRegistry

logger = logging.getLogger(__name__)
SOVEREIGN_RUNTIME_ID = "sovereign"


@dataclass
class RuntimeContext:
    runtime_id: str
    config: RuntimeConfig
    username: str = ""
    chat_id: str = ""
    trace_id: str = ""

    @property
    def memory_namespace(self) -> str:
        return self.config.memory_namespace

    @property
    def allowed_tools(self) -> list[str]:
        return self.config.tools

    def to_state_primitives(self) -> dict[str, str]:
        """
        Returns only JSON-serializable primitives for LangGraph state injection.
        NEVER put the RuntimeContext object itself into state.
        """
        return {
            "runtime_id": str(self.runtime_id),
            "runtime_namespace": str(self.config.memory_namespace),
        }


def resolve_runtime_context(
    runtime_id: str | None,
    username: str = "",
    chat_id: str = "",
    trace_id: str = "",
) -> RuntimeContext:
    strict = os.getenv("KURO_V2_STRICT_MODE", "false").lower() == "true"
    if runtime_id is None:
        if strict:
            raise ValueError("runtime_id required in KURO_V2_STRICT_MODE=true")
        logger.warning(
            "No runtime_id provided for username=%r, defaulting to sovereign",
            username,
        )
        runtime_id = SOVEREIGN_RUNTIME_ID
    config = RuntimeRegistry.get(runtime_id)
    resolved_runtime_id = config.runtime_id
    if runtime_id != resolved_runtime_id:
        logger.warning(
            "Runtime %r resolved to fallback runtime %r",
            runtime_id,
            resolved_runtime_id,
        )
    return RuntimeContext(
        runtime_id=resolved_runtime_id,
        config=config,
        username=username,
        chat_id=chat_id,
        trace_id=trace_id,
    )
