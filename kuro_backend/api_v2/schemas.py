"""Typed schemas for API V2 response, error, and control-plane contracts."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


APIErrorCode = Literal[
    "unauthorized",
    "forbidden",
    "not_found",
    "validation_error",
    "feature_disabled",
    "rate_limited",
    "provider_unavailable",
    "tool_denied",
    "memory_denied",
    "internal_error",
]


class APIErrorBody(BaseModel):
    code: APIErrorCode
    message: str
    detail: Optional[Any] = None


class APIEnvelope(BaseModel):
    status: Literal["success", "error"]
    data: Any = None
    error: Optional[APIErrorBody] = None
    trace_id: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class APIHealth(BaseModel):
    enabled: bool
    version: str = "v2"
    response_envelope: str = "status,data,error,trace_id,meta"
    error_codes: list[str] = Field(default_factory=list)
    rate_limit_enabled: bool = False
    request_size_limit_bytes: int = 0


class Principal(BaseModel):
    username: str
    roles: list[str] = Field(default_factory=list)
    workspace_roles: Dict[str, list[str]] = Field(default_factory=dict)
    is_admin: bool = False
    is_service_account: bool = False


class PaginationMeta(BaseModel):
    limit: int
    next_cursor: Optional[str] = None
    total: Optional[int] = None
