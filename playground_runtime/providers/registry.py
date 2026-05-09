"""
Provider registry.

--- Header Doc ---
Purpose: Dynamic runtime provider registry from canonical PLAYGROUND_* env values.
Caller: ProviderRouter and API endpoints.
Dependencies: config, adapters, capability registry, health monitor.
Main Functions: register/get/list_active/health_check/get_capability_spec.
Side Effects: Builds runtime adapter registry.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, List

from playground_runtime.config import PlaygroundSettings
from playground_runtime.errors import ProviderConfigurationError
from playground_runtime.providers.adapters import (
    AnthropicAdapter,
    BaseAdapter,
    DeepSeekAdapter,
    GeminiAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    OpenAICompatAdapter,
)
from playground_runtime.providers.capability_registry import CapabilityRegistry
from playground_runtime.providers.health_monitor import HealthMonitor
from playground_runtime.providers.schemas.capability_spec import CapabilitySpec

logger = logging.getLogger(__name__)


@dataclass
class RegisteredProvider:
    provider_id: str
    adapter: BaseAdapter


class ProviderRegistry:
    def __init__(self, settings: PlaygroundSettings):
        self.settings = settings
        self._providers: Dict[str, RegisteredProvider] = {}
        self._capabilities = CapabilityRegistry()
        self._health = HealthMonitor(
            failure_threshold=settings.KURO_PLAYGROUND_PROVIDER_FAILURE_THRESHOLD,
            cooldown_seconds=settings.KURO_PLAYGROUND_PROVIDER_HEALTH_INTERVAL_S,
        )

    def register(self, provider_id: str, adapter: BaseAdapter, capability: CapabilitySpec) -> None:
        self._providers[provider_id] = RegisteredProvider(provider_id=provider_id, adapter=adapter)
        self._capabilities.register(capability)

    def load_from_env(self) -> None:
        provider_cfg = self.settings.provider_env_configs()
        for provider_id, cfg in provider_cfg.items():
            if not cfg.active:
                logger.debug("[KPR] Provider '%s' inactive (missing required PLAYGROUND_* keys)", provider_id)
                continue
            adapter = self._build_adapter(provider_id, cfg)
            self.register(provider_id, adapter, self._default_capability(provider_id))

    def _build_adapter(self, provider_id: str, cfg) -> BaseAdapter:
        model = cfg.model_name or ""
        if provider_id == "openai":
            if not cfg.api_key:
                raise ProviderConfigurationError("openai provider requires API key")
            return OpenAIAdapter(api_key=cfg.api_key, default_model=model or "gpt-4o-mini")
        if provider_id == "gemini":
            if not cfg.api_key:
                raise ProviderConfigurationError("gemini provider requires API key")
            return GeminiAdapter(api_key=cfg.api_key, default_model=model or "gemini-2.0-flash")
        if provider_id == "anthropic":
            if not cfg.api_key:
                raise ProviderConfigurationError("anthropic provider requires API key")
            return AnthropicAdapter(api_key=cfg.api_key, default_model=model or "claude-3-5-sonnet-latest")
        if provider_id == "deepseek":
            if not cfg.api_key:
                raise ProviderConfigurationError("deepseek provider requires API key")
            return DeepSeekAdapter(api_key=cfg.api_key, default_model=model or "deepseek-chat")
        if provider_id == "ollama":
            return OllamaAdapter(base_url=cfg.base_url or "http://localhost:11434", default_model=model or "llama3.1:8b")

        if provider_id != "openai_compat":
            raise ProviderConfigurationError(f"unsupported provider_id '{provider_id}'")
        base_url = cfg.base_url
        if not base_url:
            raise ProviderConfigurationError("openai_compat provider requires BASE_URL")
        return OpenAICompatAdapter(
            provider_id=provider_id,
            base_url=base_url,
            api_key=cfg.api_key,
            default_model=model or "unknown-model",
        )

    def _default_capability(self, provider_id: str) -> CapabilitySpec:
        return CapabilitySpec(
            provider_id=provider_id,
            supports_text=True,
            supports_code=True,
            supports_grounding=True if provider_id in {"gemini"} else False,
            grounding_type="chunk" if provider_id in {"gemini"} else "none",
            supports_citations=True if provider_id in {"gemini"} else False,
            citation_format="provider" if provider_id in {"gemini"} else "none",
            supports_streaming=True,
            supports_tool_use=True,
            max_context_window=131072 if provider_id == "gemini" else 32768,
            exposes_visible_reasoning_traces=False,
        )

    def get(self, provider_id: str) -> BaseAdapter:
        return self._providers[provider_id].adapter

    def list_active(self) -> List[str]:
        return sorted(self._providers.keys())

    def health_check(self) -> Dict[str, bool]:
        return {pid: self._health.is_available(pid) for pid in self._providers.keys()}

    def get_capability_spec(self, provider_id: str) -> CapabilitySpec:
        return self._capabilities.get(provider_id)

    @property
    def health_monitor(self) -> HealthMonitor:
        return self._health
