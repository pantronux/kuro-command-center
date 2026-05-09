"""
OpenAI-compatible adapter.

--- Header Doc ---
Purpose: Generic adapter for OpenAI-compatible /v1/chat/completions endpoints.
Caller: provider router via ProviderRegistry.
Dependencies: requests, json, time.
Main Functions: OpenAICompatAdapter.invoke().
Side Effects: Outbound HTTP POST request.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from playground_runtime.errors import ProviderConfigurationError, ProviderExecutionError
from playground_runtime.providers.adapters.base_adapter import BaseAdapter, ProviderRequest, ProviderResponse


class OpenAICompatAdapter(BaseAdapter):
    def __init__(self, provider_id: str, base_url: str, api_key: Optional[str], default_model: str):
        self.provider_id = provider_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    def invoke(self, req: ProviderRequest) -> ProviderResponse:
        if not self.base_url:
            raise ProviderConfigurationError(f"Provider '{self.provider_id}' missing base_url")
        model = req.model or self.default_model
        if not model:
            raise ProviderConfigurationError(f"Provider '{self.provider_id}' missing model")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": req.prompt}],
            "temperature": 0,
        }
        start = time.perf_counter()
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as exc:
            raise ProviderExecutionError(f"Provider '{self.provider_id}' request failed: {exc}") from exc
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
