"""DeepSeek OpenAI-compatible HTTP adapter for Provider Registry V2."""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from typing import AsyncIterator

from kuro_backend.providers.base import BaseProvider, done_event, text_delta_event
from kuro_backend.providers.schemas import ProviderRequest, ProviderResponse, ProviderStatus, ProviderStreamEvent
from kuro_backend.providers.usage import estimate_request_usage


class DeepSeekProvider(BaseProvider):
    provider_id = "deepseek"
    display_name = "DeepSeek"
    api_key_attr = "DEEPSEEK_API_KEY"
    sdk_module_name = ""
    supports_streaming = False
    supports_tools = False
    supports_structured_output = True

    def base_url(self) -> str:
        return (
            os.getenv("KURO_DEEPSEEK_BASE_URL", "")
            or os.getenv("DEEPSEEK_BASE_URL", "")
        ).rstrip("/")

    def availability(self) -> ProviderStatus:
        status = super().availability()
        if status.available and not self.base_url():
            status.available = False
            status.reason = "missing_base_url"
        return status

    def _messages(self, request: ProviderRequest) -> list[dict]:
        messages: list[dict] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.extend({"role": msg.role, "content": msg.content} for msg in request.messages)
        return messages

    async def generate(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        start = time.perf_counter()
        url = self.base_url()
        if not url.endswith("/chat/completions"):
            url = url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model_id,
            "messages": self._messages(request),
            "temperature": float(request.temperature),
            "max_tokens": int(request.max_output_tokens),
        }

        def _call() -> dict:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key()}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))

        raw = await asyncio.to_thread(_call)
        choice = (raw.get("choices") or [{}])[0]
        content = str(((choice.get("message") or {}).get("content")) or "")
        return ProviderResponse(
            provider=self.provider_id,
            model_id=model_id,
            content=content,
            raw=raw,
            usage=estimate_request_usage(request.messages, content),
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            finish_reason=str(choice.get("finish_reason") or "stop"),
            trace_id=request.trace_id,
        )

    async def stream(self, request: ProviderRequest, *, model_id: str) -> AsyncIterator[ProviderStreamEvent]:
        response = await self.generate(request, model_id=model_id)
        if response.content:
            yield text_delta_event(response.content, trace_id=request.trace_id)
        yield done_event(trace_id=request.trace_id)
