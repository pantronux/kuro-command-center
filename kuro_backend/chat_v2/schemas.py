"""Typed schemas for additive Chat V2 APIs and streaming envelopes."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


ChatMode = Literal["default", "research", "agent", "market", "qa"]
SSEEventName = Literal[
    "trace",
    "token",
    "tool_call_start",
    "tool_call_delta",
    "tool_call_end",
    "memory_context",
    "structured_output",
    "error",
    "done",
]


class ChatSessionSettings(BaseModel):
    provider_alias: str = ""
    model_alias: str = ""
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    runtime_id: str = "sovereign"
    mode: ChatMode = "default"
    tools_enabled: bool = True
    web_search_enabled: bool = False
    memory_v3_enabled: bool = False

    @field_validator("provider_alias", "model_alias", "runtime_id")
    @classmethod
    def _short_text(cls, value: str) -> str:
        return str(value or "").strip()[:128]


class ChatSessionCreate(BaseModel):
    persona: str = "consultant"
    title: str = "New Chat"
    settings: ChatSessionSettings = Field(default_factory=ChatSessionSettings)
    workspace_id: str = "default"


class ChatSessionPatch(BaseModel):
    title: Optional[str] = None
    persona: Optional[str] = None
    archived: Optional[bool] = None
    settings: Optional[ChatSessionSettings] = None


class ChatMessageEditRequest(BaseModel):
    new_content: str = Field(..., min_length=1, max_length=32000)


class ChatMessageEditResult(BaseModel):
    chat_id: str
    message_id: int
    edit_group_id: str
    branch_id: str
    deleted_after_count: int = 0


class ChatMessageRegenerateResult(BaseModel):
    chat_id: str
    message_id: int
    deleted_msg_id: int
    parent_message_id: int
    edit_group_id: str
    preceding_user_message: Dict[str, Any]


class ChatMessagePage(BaseModel):
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    has_more: bool = False
    oldest_id: Optional[int] = None


class StreamingEnvelope(BaseModel):
    event: SSEEventName
    event_seq: int
    trace_id: str
    chat_id: str
    data: Dict[str, Any] = Field(default_factory=dict)

