"""Gemini adapter for Provider Registry V2."""
from __future__ import annotations

import time
from typing import AsyncIterator

from kuro_backend.providers.base import BaseProvider, done_event, text_delta_event
from kuro_backend.providers.schemas import ProviderRequest, ProviderResponse, ProviderStreamEvent
from kuro_backend.providers.usage import estimate_request_usage


class GeminiProvider(BaseProvider):
    provider_id = "gemini"
    display_name = "Gemini"
    api_key_attr = "GEMINI_API_KEY"
    sdk_module_name = "google.genai"
    supports_streaming = True
    supports_tools = True
    supports_structured_output = True

    async def generate(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        start = time.perf_counter()
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key())
        config_kwargs = {
            "temperature": float(request.temperature),
            "max_output_tokens": int(request.max_output_tokens),
        }
        if request.system_instruction:
            config_kwargs["system_instruction"] = request.system_instruction
        if request.structured_output_schema:
            config_kwargs["response_mime_type"] = "application/json"
        response = client.models.generate_content(
            model=model_id,
            contents=self.prompt_from_messages(request),
            config=types.GenerateContentConfig(**config_kwargs),
        )
        content = str(getattr(response, "text", "") or "")
        return ProviderResponse(
            provider=self.provider_id,
            model_id=model_id,
            content=content,
            raw=None,
            usage=estimate_request_usage(request.messages, content),
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            trace_id=request.trace_id,
        )

    async def stream(self, request: ProviderRequest, *, model_id: str) -> AsyncIterator[ProviderStreamEvent]:
        response = await self.generate(request, model_id=model_id)
        if response.content:
            yield text_delta_event(response.content, trace_id=request.trace_id)
        yield done_event(trace_id=request.trace_id)
