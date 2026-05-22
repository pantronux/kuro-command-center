"""Runtime config loader orchestration utilities."""
from __future__ import annotations

from typing import Dict

from kuro_backend.runtime.runtime_registry import RuntimeConfig, RuntimeRegistry


def load_runtime_configs(*, reload: bool = False) -> Dict[str, RuntimeConfig]:
    """Load runtime configs and return a runtime_id keyed snapshot."""
    if reload:
        RuntimeRegistry.reload()
    return {config.runtime_id: config for config in RuntimeRegistry.list_runtimes(include_stubs=True)}


def get_runtime_config(runtime_id: str) -> RuntimeConfig:
    """Return a runtime config, preserving sovereign fallback semantics."""
    return RuntimeRegistry.get(runtime_id)
