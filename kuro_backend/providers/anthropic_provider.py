"""Anthropic adapter for Provider Registry V2."""
from __future__ import annotations

import time
from typing import AsyncIterator

from kuro_backend.providers.base import BaseProvider, done_event, text_delta_event
from kuro_backend.providers.schemas import ProviderRequest, ProviderResponse, ProviderStreamEvent, ProviderUsage
from kuro_backend.providers.usage import estimate_request_usage


class AnthropicProvider(BaseProvider):
    provider_id = "anthropic"
    display_name = "Anthropic"
    api_key_attr = "ANTHROPIC_API_KEY"
    sdk_module_name = "anthropic"
    supports_streaming = True
    supports_tools = True
    supports_structured_output = False

    def _messages(self, request: ProviderRequest) -> list[dict]:
        return [
            {"role": "assistant" if msg.role == "assistant" else "user", "content": str(msg.content)}
            for msg in request.messages
        ]

    async def generate(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        start = time.perf_counter()
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.api_key())
        response = await client.messages.create(
            model=model_id,
            messages=self._messages(request),
            system=request.system_instruction or None,
            temperature=float(request.temperature),
            max_tokens=int(request.max_output_tokens),
        )
        parts = []
        for part in getattr(response, "content", []) or []:
            text = getattr(part, "text", "")
            if text:
                parts.append(str(text))
        content = "".join(parts)
        usage_raw = getattr(response, "usage", None)
        usage = ProviderUsage(
            input_tokens=int(getattr(usage_raw, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage_raw, "output_tokens", 0) or 0),
            total_tokens=int(getattr(usage_raw, "input_tokens", 0) or 0)
            + int(getattr(usage_raw, "output_tokens", 0) or 0),
        )
        if usage.total_tokens == 0:
            usage = estimate_request_usage(request.messages, content)
        return ProviderResponse(
            provider=self.provider_id,
            model_id=model_id,
            content=content,
            usage=usage,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            finish_reason=str(getattr(response, "stop_reason", "stop") or "stop"),
            trace_id=request.trace_id,
        )

    async def stream(self, request: ProviderRequest, *, model_id: str) -> AsyncIterator[ProviderStreamEvent]:
        response = await self.generate(request, model_id=model_id)
        if response.content:
            yield text_delta_event(response.content, trace_id=request.trace_id)
        yield done_event(trace_id=request.trace_id)
