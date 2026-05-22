"""Provider and model registry V2."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import AsyncIterator, Dict, Iterable, Optional, Type

from kuro_backend.config import settings
from kuro_backend.enterprise_observability.metrics import record_provider_latency_if_enabled
from kuro_backend.enterprise_observability.security_events import record_provider_error_if_enabled
from kuro_backend.providers.anthropic_provider import AnthropicProvider
from kuro_backend.providers.base import BaseProvider
from kuro_backend.providers.deepseek_provider import DeepSeekProvider
from kuro_backend.providers.errors import ModelAliasError, ProviderSafetyRefusal, ProviderUnavailableError
from kuro_backend.providers.gemini_provider import GeminiProvider
from kuro_backend.providers.openai_provider import OpenAIProvider
from kuro_backend.providers.schemas import (
    ModelAlias,
    ProviderHealth,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderStreamEvent,
)


logger = logging.getLogger(__name__)


MODEL_ALIAS_CONFIG: Dict[str, Dict[str, str]] = {
    "gemini_fast": {
        "provider": "gemini",
        "settings_attr": "KURO_MODEL_GEMINI_FAST",
        "display_name": "Gemini Fast",
    },
    "openai_nano": {
        "provider": "openai",
        "settings_attr": "KURO_MODEL_OPENAI_NANO",
        "display_name": "OpenAI Nano",
    },
    "claude_fast": {
        "provider": "anthropic",
        "settings_attr": "KURO_MODEL_CLAUDE_FAST",
        "display_name": "Claude Fast",
    },
    "deepseek_fast": {
        "provider": "deepseek",
        "settings_attr": "KURO_MODEL_DEEPSEEK_FAST",
        "display_name": "DeepSeek Fast",
    },
}


PROVIDER_CLASSES: Dict[str, Type[BaseProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepSeekProvider,
}


def is_provider_registry_enabled() -> bool:
    return bool(getattr(settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", False))


class ProviderRegistryV2:
    def __init__(
        self,
        *,
        provider_classes: Optional[Dict[str, Type[BaseProvider]]] = None,
    ) -> None:
        self.provider_classes = dict(provider_classes or PROVIDER_CLASSES)
        self._providers: Dict[str, BaseProvider] = {}

    def provider(self, provider_id: str) -> BaseProvider:
        normalized = str(provider_id or "").strip().lower()
        if normalized not in self._providers:
            cls = self.provider_classes.get(normalized)
            if cls is None:
                raise ProviderUnavailableError(f"unknown provider: {provider_id}")
            self._providers[normalized] = cls()
        return self._providers[normalized]

    def provider_statuses(self) -> Dict[str, ProviderStatus]:
        statuses: Dict[str, ProviderStatus] = {}
        for provider_id in self.provider_classes:
            try:
                statuses[provider_id] = self.provider(provider_id).availability()
            except Exception as exc:
                statuses[provider_id] = ProviderStatus(
                    provider=provider_id,
                    display_name=provider_id,
                    available=False,
                    reason=f"status_error:{str(exc)[:80]}",
                    configured=False,
                    dependency_available=False,
                )
        return statuses

    def get_enabled_providers(self) -> Dict[str, ProviderStatus]:
        if not is_provider_registry_enabled():
            return {}
        return {
            provider_id: status
            for provider_id, status in self.provider_statuses().items()
            if status.available
        }

    def resolve_model_alias(self, alias: str) -> ModelAlias:
        normalized = str(alias or "").strip() or str(getattr(settings, "KURO_DEFAULT_MODEL_ALIAS", "gemini_fast"))
        config = MODEL_ALIAS_CONFIG.get(normalized)
        if not config:
            raise ModelAliasError(f"unknown model alias: {alias}")
        model_id = str(getattr(settings, config["settings_attr"], "") or "").strip()
        if not model_id:
            raise ModelAliasError(f"model alias has no configured model_id: {normalized}")
        provider_id = config["provider"]
        status = self.provider_statuses().get(provider_id)
        return ModelAlias(
            alias=normalized,
            provider=provider_id,
            model_id=model_id,
            display_name=config["display_name"],
            enabled=bool(is_provider_registry_enabled() and status and status.available),
        )

    def get_model_aliases(self, *, public_only: bool = False) -> Dict[str, ModelAlias]:
        aliases: Dict[str, ModelAlias] = {}
        for alias in MODEL_ALIAS_CONFIG:
            try:
                resolved = self.resolve_model_alias(alias)
            except ModelAliasError:
                continue
            if public_only and not resolved.enabled:
                continue
            aliases[alias] = resolved
        return aliases

    def get_provider_for_alias(self, alias: str) -> BaseProvider:
        resolved = self.resolve_model_alias(alias)
        provider = self.provider(resolved.provider)
        status = provider.availability()
        if not is_provider_registry_enabled():
            raise ProviderUnavailableError("provider registry is disabled")
        if not status.available:
            raise ProviderUnavailableError(f"provider unavailable: {resolved.provider} ({status.reason})")
        return provider

    def health_check(self) -> ProviderHealth:
        statuses = self.provider_statuses()
        aliases = self.get_model_aliases(public_only=False)
        return ProviderHealth(
            enabled=is_provider_registry_enabled(),
            providers=statuses,
            aliases=aliases,
        )

    def public_models(self) -> dict:
        aliases = self.get_model_aliases(public_only=True) if is_provider_registry_enabled() else {}
        return {
            "enabled": is_provider_registry_enabled(),
            "models": [
                {
                    "alias": alias.alias,
                    "provider": alias.provider,
                    "display_name": alias.display_name,
                }
                for alias in aliases.values()
            ],
        }

    async def route_generate(
        self,
        request: ProviderRequest,
        *,
        fallback_aliases: Optional[Iterable[str]] = None,
        timeout_s: float = 30.0,
        retry_count: int = 0,
    ) -> ProviderResponse:
        aliases = self._route_aliases(request.model_alias, fallback_aliases)
        last_error: Optional[Exception] = None
        for index, alias in enumerate(aliases):
            resolved_provider = "unknown"
            started = time.monotonic()
            try:
                resolved = self.resolve_model_alias(alias)
                resolved_provider = resolved.provider
                provider = self.get_provider_for_alias(alias)
                routed_request = request.model_copy(update={"model_alias": alias, "model_id": request.model_id or resolved.model_id})
                attempts = max(1, int(retry_count or 0) + 1)
                for attempt in range(attempts):
                    try:
                        response = await asyncio.wait_for(
                            provider.generate(routed_request, model_id=routed_request.model_id),
                            timeout=timeout_s,
                        )
                        record_provider_latency_if_enabled(
                            round((time.monotonic() - started) * 1000.0, 3),
                            provider=resolved_provider,
                            model_alias=alias,
                            trace_id=request.trace_id,
                        )
                        return response
                    except ProviderSafetyRefusal:
                        raise
                    except Exception as exc:
                        last_error = exc
                        if attempt >= attempts - 1:
                            raise
            except ProviderSafetyRefusal:
                raise
            except Exception as exc:
                logger.warning("Provider route failed alias=%s error=%s", alias, exc)
                last_error = exc
                fallback_alias = aliases[index + 1] if index + 1 < len(aliases) else ""
                record_provider_error_if_enabled(
                    resolved_provider,
                    str(exc)[:500],
                    model_alias=alias,
                    fallback_alias=fallback_alias,
                    trace_id=request.trace_id,
                )
                continue
        raise ProviderUnavailableError(f"all providers failed: {last_error}")

    async def route_stream(
        self,
        request: ProviderRequest,
        *,
        fallback_aliases: Optional[Iterable[str]] = None,
        timeout_s: float = 30.0,
    ) -> AsyncIterator[ProviderStreamEvent]:
        aliases = self._route_aliases(request.model_alias, fallback_aliases)
        last_error: Optional[Exception] = None
        for index, alias in enumerate(aliases):
            resolved_provider = "unknown"
            started = time.monotonic()
            try:
                resolved = self.resolve_model_alias(alias)
                resolved_provider = resolved.provider
                provider = self.get_provider_for_alias(alias)
                routed_request = request.model_copy(update={"model_alias": alias, "model_id": request.model_id or resolved.model_id})
                async for event in provider.stream(routed_request, model_id=routed_request.model_id):
                    yield event
                record_provider_latency_if_enabled(
                    round((time.monotonic() - started) * 1000.0, 3),
                    provider=resolved_provider,
                    model_alias=alias,
                    trace_id=request.trace_id,
                    stream=True,
                )
                return
            except ProviderSafetyRefusal:
                raise
            except Exception as exc:
                logger.warning("Provider stream failed alias=%s error=%s", alias, exc)
                last_error = exc
                fallback_alias = aliases[index + 1] if index + 1 < len(aliases) else ""
                record_provider_error_if_enabled(
                    resolved_provider,
                    str(exc)[:500],
                    model_alias=alias,
                    fallback_alias=fallback_alias,
                    trace_id=request.trace_id,
                )
                continue
        yield ProviderStreamEvent(
            event_type="error",
            error=f"all providers failed: {last_error}",
            trace_id=request.trace_id,
        )
        yield ProviderStreamEvent(event_type="done", done=True, trace_id=request.trace_id)

    def _route_aliases(self, primary_alias: str, fallback_aliases: Optional[Iterable[str]]) -> list[str]:
        primary = (
            str(primary_alias or "").strip()
            or str(getattr(settings, "KURO_DEFAULT_MODEL_ALIAS", "gemini_fast") or "gemini_fast")
        )
        configured_fallbacks = [
            part.strip()
            for part in str(os.getenv("KURO_PROVIDER_FALLBACK_ALIASES", "gemini_fast")).split(",")
            if part.strip()
        ]
        return list(dict.fromkeys([primary, *(fallback_aliases or configured_fallbacks)]))


_REGISTRY: Optional[ProviderRegistryV2] = None


def get_provider_registry() -> ProviderRegistryV2:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ProviderRegistryV2()
    return _REGISTRY


def reset_provider_registry_for_tests() -> None:
    global _REGISTRY
    _REGISTRY = None
