"""Typed schemas for Memory V3 core."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


MEMORY_TYPES: tuple[str, ...] = (
    "ephemeral_context",
    "working_memory",
    "episodic_memory",
    "semantic_memory",
    "procedural_memory",
    "operational_memory",
    "evidence_memory",
    "reflective_memory",
    "task_memory",
    "market_signal_memory",
    "user_preference_memory",
    "system_policy_memory",
)

MEMORY_STATUSES: tuple[str, ...] = (
    "active",
    "deprecated",
    "conflicted",
    "expired",
    "redacted",
)

ACCESS_TYPES: tuple[str, ...] = ("read", "write", "update", "delete", "redact")


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MemoryScope(BaseModel):
    workspace_id: str = "default"
    username: str
    runtime_id: str = "sovereign"
    persona_scope: str = "consultant"
    chat_id: str
    source_type: str = "conversation"
    source_id: str

    @field_validator(
        "workspace_id",
        "username",
        "runtime_id",
        "persona_scope",
        "chat_id",
        "source_type",
        "source_id",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("scope value must not be empty")
        return cleaned[:256]


class MemoryEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("mevt"))
    event_type: str
    idempotency_key: str
    workspace_id: str
    username: str
    runtime_id: str
    persona_scope: str
    chat_id: str
    source_type: str
    source_id: str
    payload_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
    trace_id: str = ""


class MemoryItem(BaseModel):
    memory_id: str = Field(default_factory=lambda: new_id("memv3"))
    canonical_key: str
    memory_type: str
    status: Literal["active", "deprecated", "conflicted", "expired", "redacted"] = "active"
    content: str
    normalized_summary: str = ""
    confidence_score: float = Field(default=0.75, ge=0.0, le=1.0)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    sensitivity_level: Literal["none", "low", "medium", "high"] = "low"
    workspace_id: str
    username: str
    runtime_id: str
    persona_scope: str
    chat_id_nullable: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    expires_at: Optional[str] = None
    source_event_id: str
    provenance_json: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("memory_type")
    @classmethod
    def _valid_memory_type(cls, value: str) -> str:
        if value not in MEMORY_TYPES:
            raise ValueError(f"unsupported memory_type: {value}")
        return value


class MemoryAssertion(BaseModel):
    assertion_id: str = Field(default_factory=lambda: new_id("masrt"))
    memory_id: str
    subject: str
    predicate: str
    object: str
    qualifiers_json: Dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence_refs_json: List[Dict[str, Any]] = Field(default_factory=list)


class MemoryWriteRequest(BaseModel):
    workspace_id: str = "default"
    username: str
    runtime_id: str = "sovereign"
    persona_scope: str = "consultant"
    chat_id: str
    source_type: str = "conversation"
    source_id: str
    content: str = Field(..., min_length=1)
    memory_type: Optional[str] = None
    normalized_summary: Optional[str] = None
    confidence_score: float = Field(default=0.75, ge=0.0, le=1.0)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    sensitivity_level: Optional[Literal["none", "low", "medium", "high"]] = None
    canonical_key: Optional[str] = None
    trace_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def scope(self) -> MemoryScope:
        return MemoryScope(
            workspace_id=self.workspace_id,
            username=self.username,
            runtime_id=self.runtime_id,
            persona_scope=self.persona_scope,
            chat_id=self.chat_id,
            source_type=self.source_type,
            source_id=self.source_id,
        )


class MemoryWriteResult(BaseModel):
    event_id: str
    memory_id: str
    created: bool = True
    idempotent: bool = False
    status: str = "active"
    conflict_ids: List[str] = Field(default_factory=list)
    canonical_key: str


class MemoryReadRequest(BaseModel):
    workspace_id: str = "default"
    username: str
    runtime_id: str = "sovereign"
    persona_scope: str = "consultant"
    chat_id: Optional[str] = None
    query: str = ""
    memory_type: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    include_cross_chat: bool = False
    trace_id: str = ""


class MemoryReadResult(BaseModel):
    items: List[MemoryItem] = Field(default_factory=list)
    query_hash: str = ""
    access_logged: bool = False


class MemoryConflict(BaseModel):
    conflict_id: str = Field(default_factory=lambda: new_id("mconf"))
    memory_id_a: str
    memory_id_b: str
    conflict_type: str = "contradiction"
    status: str = "open"
    resolution_strategy: str = ""
    resolution_notes: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    resolved_at: Optional[str] = None


class MemoryPolicy(BaseModel):
    policy_id: str
    memory_type: str
    retention_days: Optional[int] = None
    sensitivity_level: Literal["none", "low", "medium", "high"] = "low"
    requires_review: bool = False
