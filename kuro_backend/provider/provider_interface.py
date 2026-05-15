"""Provider interface contract for LLM adapters."""

# --- Header Doc ---
# Purpose: Unified provider abstraction for Gemini/OpenAI/etc adapters.
# Caller: provider_router.py, langgraph_core.py.
# Dependencies: abc, pydantic, typing.
# Main Functions: AIProvider.generate(), AIProvider.stream().
# Side Effects: None.

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel, Field


class ProviderRequest(BaseModel):
    prompt: str
    system_prompt: str = ""
    max_tokens: int = 8192
    temperature: float = 0.7
    tools: list[dict] = Field(default_factory=list)
    structured_output_schema: Optional[dict] = None
    context_messages: list[dict] = Field(default_factory=list)


class ProviderUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ProviderResponse(BaseModel):
    provider: str
    model: str
    content: str
    structured: Optional[Any] = None
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    latency_ms: float = 0.0
    finish_reason: str = "stop"
    raw: Optional[Any] = None


class ProviderStreamChunk(BaseModel):
    content: str
    is_final: bool = False
    finish_reason: Optional[str] = None


class AIProvider(ABC):
    provider_id: str = ""
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_vision: bool = False
    supports_streaming: bool = True

    def is_available(self) -> bool:
        return True

    @abstractmethod
    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamChunk]:
        raise NotImplementedError
