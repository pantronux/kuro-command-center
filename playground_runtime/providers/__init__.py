"""
KPR provider runtime.

--- Header Doc ---
Purpose: Provider registration, routing, and capability management.
Caller: playground execution pipeline.
Dependencies: providers.registry, providers.router.
Main Functions: ProviderRegistry, ProviderRouter.
Side Effects: None.
"""

from .registry import ProviderRegistry
from .router import ProviderRouter

__all__ = ["ProviderRegistry", "ProviderRouter"]
