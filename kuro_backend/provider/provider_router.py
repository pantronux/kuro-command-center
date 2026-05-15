"""Provider router for primary and fallback model routing."""

# --- Header Doc ---
# Purpose: Runtime-aware provider routing with primary->fallback chain.
# Caller: langgraph_core.py non-stream generation path.
# Dependencies: provider_interface.py, gemini_provider.py, runtime_registry.py.
# Main Functions: ProviderRouter.route().
# Side Effects: Provider API calls.

from __future__ import annotations

import logging
import os

from kuro_backend.provider.gemini_provider import GeminiProvider
from kuro_backend.provider.provider_interface import AIProvider, ProviderRequest
from kuro_backend.runtime.runtime_registry import RuntimeConfig

logger = logging.getLogger(__name__)

PROVIDER_MAP: dict[str, type[AIProvider]] = {
    "gemini": GeminiProvider,
}


class ProviderRouter:
    def __init__(self, runtime_config: RuntimeConfig):
        self.runtime_config = runtime_config

    @staticmethod
    def is_enabled() -> bool:
        return os.getenv("KURO_PROVIDER_ROUTER_ENABLED", "false").lower() == "true"

    def _get_provider(self, provider_id: str) -> AIProvider | None:
        cls = PROVIDER_MAP.get(provider_id)
        if cls is None:
            logger.warning("Provider %r not in PROVIDER_MAP", provider_id)
            return None
        instance = cls()
        if not instance.is_available():
            logger.warning("Provider %r unavailable (likely API key missing)", provider_id)
            return None
        return instance

    async def route(self, request: ProviderRequest):
        primary = (
            self.runtime_config.allowed_providers[0]
            if self.runtime_config.allowed_providers
            else "gemini"
        )
        provider_ids = list(
            dict.fromkeys([primary, self.runtime_config.fallback_provider or "gemini"])
        )
        last_error = None
        for provider_id in provider_ids:
            provider = self._get_provider(provider_id)
            if provider is None:
                continue
            try:
                response = await provider.generate(request)
                logger.info(
                    "ProviderRouter succeeded provider=%s latency=%.2fms",
                    provider_id,
                    float(response.latency_ms or 0.0),
                )
                return response
            except Exception as exc:
                logger.warning("ProviderRouter failed provider=%s err=%s", provider_id, exc)
                last_error = exc
        raise RuntimeError(
            f"All providers failed for runtime={self.runtime_config.runtime_id}: {last_error}"
        )
