"""Kuro services layer — single data writer: `core_service`.

--- Header Doc ---
Purpose: Package-level re-export of the services layer entry points.
Caller: Any module importing `kuro_backend.services`.
Dependencies: services.core_service.
Main Functions: re-exports `core_service`.
Side Effects: Imports core_service (which triggers schema init lazily).
"""

from kuro_backend.services import core_service

__all__ = ["core_service"]
