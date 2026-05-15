"""Gemini provider adapter implementation."""

# --- Header Doc ---
# Purpose: Gemini provider wrapper using existing llm_utils helper.
# Caller: ProviderRouter when feature flag is enabled.
# Dependencies: provider_interface.py, llm_utils.py.
# Main Functions: GeminiProvider.generate().
# Side Effects: Calls Gemini API only when enabled and configured.

from __future__ import annotations

import logging
import os
import time
from typing import AsyncIterator

from kuro_backend.config import settings
from kuro_backend.provider.provider_interface import (
    AIProvider,
    ProviderRequest,
    ProviderResponse,
    ProviderStreamChunk,
    ProviderUsage,
)

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    provider_id = "gemini"
    supports_tools = True
    supports_structured_output = True
    supports_vision = True
    supports_streaming = True  # streaming migration intentionally deferred

    def is_available(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        start = time.perf_counter()
        try:
            from kuro_backend import llm_utils

            if not hasattr(llm_utils, "generate_text"):
                raise AttributeError("generate_text not found in llm_utils")
            content = await llm_utils.generate_text(
                request.prompt,
                system_prompt=request.system_prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
            latency_ms = (time.perf_counter() - start) * 1000.0
            return ProviderResponse(
                provider="gemini",
                model=os.getenv("GEMINI_MODEL_NAME", settings.MODEL_NAME),
                content=content or "",
                latency_ms=latency_ms,
                usage=ProviderUsage(),
            )
        except Exception as exc:
            logger.error("GeminiProvider.generate failed: %s", exc)
            raise

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamChunk]:
        raise NotImplementedError(
            "GeminiProvider.stream() is not implemented in Phase 5. "
            "Production streaming still uses the legacy path."
        )
