"""Typed schemas for Provider Registry V2."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


ProviderId = Literal["gemini", "openai", "anthropic", "deepseek", "ollama"]
ProviderEventType = Literal[
    "token",
    "tool_call_start",
    "tool_call_delta",
    "tool_call_end",
    "structured_output",
    "error",
    "done",
]


class ProviderMessage(BaseModel):
    role: str
    content: Any


class ProviderRequest(BaseModel):
    messages: List[ProviderMessage] = Field(default_factory=list)
    system_instruction: str = ""
    model_alias: str = "gemini_fast"
    model_id: str = ""
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=8192, ge=1, le=200000)
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    structured_output_schema: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""

    @field_validator("model_alias", "model_id", "trace_id")
    @classmethod
    def _short_text(cls, value: str) -> str:
        return str(value or "").strip()[:256]

    @classmethod
    def from_prompt(cls, prompt: str, **kwargs: Any) -> "ProviderRequest":
        messages = kwargs.pop("messages", None) or [{"role": "user", "content": prompt}]
        return cls(messages=messages, **kwargs)


class ProviderUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class ProviderResponse(BaseModel):
    provider: str
    model_id: str
    content: str = ""
    structured: Optional[Any] = None
    raw: Optional[Any] = None
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    latency_ms: float = 0.0
    finish_reason: str = "stop"
    safety: Dict[str, Any] = Field(default_factory=dict)
    grounding: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""


class ProviderStreamEvent(BaseModel):
    event_type: ProviderEventType
    delta: str = ""
    content: str = ""
    tool_call: Optional[Dict[str, Any]] = None
    usage: Optional[ProviderUsage] = None
    raw: Optional[Any] = None
    error: Optional[str] = None
    done: bool = False
    trace_id: str = ""


class ProviderStatus(BaseModel):
    provider: str
    display_name: str
    available: bool = False
    reason: str = "disabled"
    configured: bool = False
    dependency_available: bool = True
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_structured_output: bool = False


class ModelAlias(BaseModel):
    alias: str
    provider: str
    model_id: str
    display_name: str
    enabled: bool = False


class ProviderHealth(BaseModel):
    enabled: bool = False
    providers: Dict[str, ProviderStatus] = Field(default_factory=dict)
    aliases: Dict[str, ModelAlias] = Field(default_factory=dict)
