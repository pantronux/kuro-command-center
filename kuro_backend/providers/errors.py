"""Provider Registry V2 errors."""
from __future__ import annotations


class ProviderRegistryError(RuntimeError):
    """Base provider registry error."""


class ProviderUnavailableError(ProviderRegistryError):
    """Raised when a provider is not available for routing."""


class ModelAliasError(ProviderRegistryError):
    """Raised when a model alias cannot be resolved."""


class ProviderSafetyRefusal(ProviderRegistryError):
    """Raised for provider safety refusals that should not be retried blindly."""
