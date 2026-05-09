"""
KPR custom errors.

--- Header Doc ---
Purpose: Define KPR-specific exception hierarchy without Kuro Core coupling.
Caller: governance, providers, db, api.
Dependencies: stdlib only.
Main Functions: PlaygroundError, PlaygroundIsolationError.
Side Effects: None.
"""


class PlaygroundError(Exception):
    """Base exception for playground runtime."""


class PlaygroundIsolationError(PlaygroundError):
    """Raised when isolation boundary is violated."""


class ProviderConfigurationError(PlaygroundError):
    """Raised when a provider is not configured correctly."""


class ProviderExecutionError(PlaygroundError):
    """Raised when a provider request fails."""
