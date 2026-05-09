"""
Gemini adapter.

--- Header Doc ---
Purpose: Gemini adapter using Google's OpenAI-compat endpoint.
Caller: provider registry.
Dependencies: requests, base_adapter.
Main Functions: GeminiAdapter.
Side Effects: Outbound HTTP calls.
"""

from __future__ import annotations

import time
from typing import Any, Dict

import requests

from playground_runtime.errors import ProviderConfigurationError, ProviderExecutionError
from playground_runtime.providers.adapters.base_adapter import BaseAdapter, ProviderRequest, ProviderResponse


class GeminiAdapter(BaseAdapter):
    def __init__(self, api_key: str, default_model: str = "gemini-2.0-flash"):
        self.provider_id = "gemini"
        self.api_key = api_key
        self.default_model = default_model
        # Google OpenAI-compat endpoint:
        # POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/openai"

    def invoke(self, req: ProviderRequest) -> ProviderResponse:
        if not self.api_key:
            raise ProviderConfigurationError("Provider 'gemini' missing API key")

        model = req.model or self.default_model
        if not model:
            raise ProviderConfigurationError("Provider 'gemini' missing model")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": req.prompt}],
            "temperature": 0,
        }
        start = time.perf_counter()
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as exc:
            raise ProviderExecutionError(f"Provider 'gemini' request failed: {exc}") from exc
        latency_ms = (time.perf_counter() - start) * 1000

        choice = (raw.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = raw.get("usage") or {}

        return ProviderResponse(
            provider_id=self.provider_id,
            model_id=model,
            model_version=str(raw.get("model", model)),
            request_id=str(raw.get("id") or self.build_request_id()),
            raw_json=raw,
            response_text=message.get("content"),
            finish_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency_ms,
            collected_at_utc=self.now_utc(),
        )
