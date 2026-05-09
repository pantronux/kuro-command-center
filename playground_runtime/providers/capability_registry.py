"""
Capability registry.

--- Header Doc ---
Purpose: Maintain provider capability specifications for runtime decisions.
Caller: provider registry and report generation.
Dependencies: capability_spec dataclass.
Main Functions: CapabilityRegistry methods.
Side Effects: None.
"""

from __future__ import annotations

from typing import Dict

from playground_runtime.providers.schemas.capability_spec import CapabilitySpec


class CapabilityRegistry:
    def __init__(self):
        self._capabilities: Dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> None:
        self._capabilities[spec.provider_id] = spec

    def get(self, provider_id: str) -> CapabilitySpec:
        return self._capabilities[provider_id]

    def list_all(self) -> Dict[str, CapabilitySpec]:
        return dict(self._capabilities)
