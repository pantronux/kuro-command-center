"""Typed schemas for the governed Tool Runtime V2 surface."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


RiskLevel = Literal["low", "medium", "high", "critical"]
ToolCategory = Literal[
    "search",
    "research",
    "productivity",
    "agent",
    "execution",
]
ApprovalStatus = Literal["pending", "approved", "denied", "expired"]


def tools_v2_db_path() -> Path:
    configured = os.getenv("KURO_TOOLS_V2_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    working_dir = os.getenv("WORKING_DIR", "").strip()
    root = Path(working_dir).expanduser() if working_dir else Path(__file__).resolve().parents[2]
    return root / "kuro_tools_v2.db"


class ToolDefinition(BaseModel):
    tool_id: str
    display_name: str
    description: str
    category: ToolCategory
    risk_level: RiskLevel
    requires_approval: bool = False
    requires_admin: bool = False
    allowed_runtime_ids: List[str] = Field(default_factory=lambda: ["sovereign"])
    allowed_roles: List[str] = Field(default_factory=lambda: ["user", "admin"])
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    timeout_s: int = Field(default=30, ge=1, le=900)
    budget_cost: int = Field(default=1, ge=0, le=100)
    enabled_flag: str = ""

    @field_validator("tool_id", "display_name", "enabled_flag")
    @classmethod
    def _short_text(cls, value: str) -> str:
        return str(value or "").strip()[:128]


class ToolActor(BaseModel):
    username: str
    roles: List[str] = Field(default_factory=lambda: ["user"])
    runtime_id: str = "sovereign"
    workspace_id: str = "default"
    is_admin: bool = False

    @field_validator("username", "runtime_id", "workspace_id")
    @classmethod
    def _clean_id(cls, value: str) -> str:
        return str(value or "").strip()[:128]


class ToolExecutionRequest(BaseModel):
    input: Dict[str, Any] = Field(default_factory=dict)
    runtime_id: str = "sovereign"
    workspace_id: str = "default"
    approval_id: Optional[str] = None
    idempotency_key: str = ""
    trace_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime_id", "workspace_id", "approval_id", "idempotency_key", "trace_id")
    @classmethod
    def _short_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return str(value or "").strip()[:256]


class NormalizedSource(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""
    source_type: str = "web"
    published_at: Optional[str] = None
    retrieved_at: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ToolExecutionResult(BaseModel):
    ok: bool
    tool_id: str
    trace_id: str
    status: str
    output: Dict[str, Any] = Field(default_factory=dict)
    sources: List[NormalizedSource] = Field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    approval_required: bool = False
    approval_id: Optional[str] = None
    audit_id: Optional[int] = None
    duration_ms: float = 0.0


class ToolApprovalRequest(BaseModel):
    approval_id: str
    tool_id: str
    username: str
    runtime_id: str
    workspace_id: str
    risk_level: RiskLevel
    reason: str = ""
    status: ApprovalStatus = "pending"
    input_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    expires_at: Optional[str] = None


class ToolAuditEvent(BaseModel):
    audit_id: Optional[int] = None
    event_type: str
    tool_id: str = ""
    username: str = ""
    runtime_id: str = ""
    workspace_id: str = ""
    trace_id: str = ""
    risk_level: str = ""
    status: str = ""
    approval_id: Optional[str] = None
    payload_json: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: str = ""


class DeepResearchJob(BaseModel):
    job_id: str
    username: str
    workspace_id: str = "default"
    query: str
    status: str = "queued"
    plan: Dict[str, Any] = Field(default_factory=dict)
    sources: List[NormalizedSource] = Field(default_factory=list)
    reliability_scores: List[Dict[str, Any]] = Field(default_factory=list)
    report_markdown: str = ""
    exportable_report: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: str
    updated_at: str


class DeepResearchJobRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    workspace_id: str = "default"
    max_sources: int = Field(default=5, ge=1, le=20)


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    workspace_id: str = "default"
    due_at: Optional[str] = None
    recurrence_rule: Optional[str] = None
    source_chat_id: Optional[str] = None
    source_message_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskPatchRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    due_at: Optional[str] = None
    recurrence_rule: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ReminderCreateRequest(BaseModel):
    remind_at: str = Field(..., min_length=1, max_length=128)
    task_id: Optional[str] = None
    username: Optional[str] = None
    channel: Literal["web", "telegram", "both"] = "web"
    workspace_id: str = "default"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReminderPatchRequest(BaseModel):
    remind_at: Optional[str] = None
    channel: Optional[Literal["web", "telegram", "both"]] = None
    status: Optional[str] = None
    attempt_count: Optional[int] = Field(default=None, ge=0)
    last_error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
