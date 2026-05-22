"""OpenAI adapter for Provider Registry V2."""
from __future__ import annotations

import time
from typing import AsyncIterator

from kuro_backend.providers.base import BaseProvider, done_event, text_delta_event
from kuro_backend.providers.schemas import ProviderRequest, ProviderResponse, ProviderStreamEvent, ProviderUsage


class OpenAIProvider(BaseProvider):
    provider_id = "openai"
    display_name = "OpenAI"
    api_key_attr = "OPENAI_API_KEY"
    sdk_module_name = "openai"
    supports_streaming = True
    supports_tools = True
    supports_structured_output = True

    def _messages(self, request: ProviderRequest) -> list[dict]:
        messages: list[dict] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.extend({"role": msg.role, "content": msg.content} for msg in request.messages)
        return messages

    async def generate(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        start = time.perf_counter()
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key())
        response = await client.chat.completions.create(
            model=model_id,
            messages=self._messages(request),
            temperature=float(request.temperature),
            max_tokens=int(request.max_output_tokens),
        )
        choice = response.choices[0] if getattr(response, "choices", None) else None
        content = str(getattr(getattr(choice, "message", None), "content", "") or "")
        usage_raw = getattr(response, "usage", None)
        usage = ProviderUsage(
            input_tokens=int(getattr(usage_raw, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage_raw, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage_raw, "total_tokens", 0) or 0),
        )
        return ProviderResponse(
            provider=self.provider_id,
            model_id=model_id,
            content=content,
            usage=usage,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            finish_reason=str(getattr(choice, "finish_reason", "stop") or "stop"),
            trace_id=request.trace_id,
        )

    async def stream(self, request: ProviderRequest, *, model_id: str) -> AsyncIterator[ProviderStreamEvent]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key())
        stream = await client.chat.completions.create(
            model=model_id,
            messages=self._messages(request),
            temperature=float(request.temperature),
            max_tokens=int(request.max_output_tokens),
            stream=True,
        )
        async for event in stream:
            choice = event.choices[0] if getattr(event, "choices", None) else None
            delta = getattr(getattr(choice, "delta", None), "content", "") if choice else ""
            if delta:
                yield text_delta_event(str(delta), trace_id=request.trace_id)
        yield done_event(trace_id=request.trace_id)
