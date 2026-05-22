"""Base classes for Provider Registry V2 adapters."""
from __future__ import annotations

import importlib.util
import os
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from kuro_backend.config import settings
from kuro_backend.providers.schemas import (
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderStreamEvent,
)


class BaseProvider(ABC):
    provider_id: str = ""
    display_name: str = ""
    api_key_attr: str = ""
    sdk_module_name: str = ""
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_structured_output: bool = False

    def dependency_available(self) -> bool:
        if not self.sdk_module_name:
            return True
        return importlib.util.find_spec(self.sdk_module_name) is not None

    def api_key(self) -> str:
        if self.api_key_attr:
            return str(getattr(settings, self.api_key_attr, "") or os.getenv(self.api_key_attr, "") or "")
        return ""

    def is_configured(self) -> bool:
        return bool(self.api_key().strip())

    def availability(self) -> ProviderStatus:
        dependency_available = self.dependency_available()
        configured = self.is_configured()
        if not dependency_available:
            reason = "unavailable_dependency"
        elif not configured:
            reason = "missing_api_key"
        else:
            reason = "available"
        return ProviderStatus(
            provider=self.provider_id,
            display_name=self.display_name or self.provider_id,
            available=dependency_available and configured,
            reason=reason,
            configured=configured,
            dependency_available=dependency_available,
            supports_streaming=self.supports_streaming,
            supports_tools=self.supports_tools,
            supports_structured_output=self.supports_structured_output,
        )

    def is_available(self) -> bool:
        return self.availability().available

    def resolve_model_id(self, request: ProviderRequest, fallback_model_id: str) -> str:
        return (request.model_id or fallback_model_id or "").strip()

    def prompt_from_messages(self, request: ProviderRequest) -> str:
        return "\n".join(str(message.content) for message in request.messages if message.content is not None)

    @abstractmethod
    async def generate(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream(self, request: ProviderRequest, *, model_id: str) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError


def text_delta_event(text: str, *, trace_id: str = "") -> ProviderStreamEvent:
    return ProviderStreamEvent(event_type="token", delta=text, content=text, trace_id=trace_id)


def done_event(*, trace_id: str = "") -> ProviderStreamEvent:
    return ProviderStreamEvent(event_type="done", done=True, trace_id=trace_id)


def error_event(error: str, *, trace_id: str = "") -> ProviderStreamEvent:
    return ProviderStreamEvent(event_type="error", error=error, trace_id=trace_id)
