"""Schemas and redaction helpers for enterprise observability."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


SecurityEventType = Literal[
    "prompt_injection_detected",
    "memory_poisoning_suspected",
    "tool_denied",
    "excessive_agency_blocked",
    "sensitive_info_blocked",
    "cross_runtime_access_attempt",
    "cross_user_access_attempt",
    "provider_error",
    "schema_validation_failed",
]


MetricType = Literal["counter", "latency", "gauge"]
EvalStatus = Literal["pass", "fail", "degraded"]


SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "authorization",
    "auth",
    "cookie",
    "credential",
    "private_key",
    "bearer",
)

PROMPT_KEY_FRAGMENTS = (
    "prompt",
    "messages",
    "message_text",
    "user_input",
    "input_text",
    "completion",
    "response_text",
    "raw_response",
)

SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{12,}|api[_-]?key|bearer\s+[a-z0-9._-]{8,}|secret[-_:][a-z0-9._-]+)"
)


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def safe_json_dumps(payload: Any) -> str:
    return json.dumps(redact_metadata(payload), ensure_ascii=False, sort_keys=True)


def safe_json_loads(payload: str | None, fallback: Any = None) -> Any:
    if not payload:
        return fallback if fallback is not None else {}
    try:
        return json.loads(payload)
    except Exception:
        return fallback if fallback is not None else {}


def _safe_prompt_logging_enabled() -> bool:
    return os.getenv("KURO_OBSERVABILITY_LOG_PROMPTS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _key_contains(key: str, fragments: tuple[str, ...]) -> bool:
    normalized = str(key or "").strip().lower()
    return any(fragment in normalized for fragment in fragments)


def _known_secret_values() -> list[str]:
    values: list[str] = []
    for key, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if _key_contains(key, SENSITIVE_KEY_FRAGMENTS):
            values.append(str(value))
    return values


def _redact_text(key: str, value: str, *, max_length: int) -> str:
    if _key_contains(key, SENSITIVE_KEY_FRAGMENTS):
        return "[redacted]"
    if _key_contains(key, PROMPT_KEY_FRAGMENTS) and not _safe_prompt_logging_enabled():
        return f"[redacted_text:length={len(value)}]"
    if SECRET_VALUE_RE.search(value):
        return "[redacted]"
    for secret in _known_secret_values():
        if secret and secret in value:
            return "[redacted]"
    if len(value) > max_length:
        return value[:max_length] + "...[truncated]"
    return value


def redact_metadata(payload: Any, *, parent_key: str = "", depth: int = 0, max_length: int = 500) -> Any:
    if depth > 8:
        return "[redacted_depth]"
    if payload is None or isinstance(payload, (bool, int, float)):
        return payload
    if isinstance(payload, str):
        return _redact_text(parent_key, payload, max_length=max_length)
    if isinstance(payload, dict):
        redacted: Dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            redacted[key_text] = redact_metadata(
                value,
                parent_key=key_text,
                depth=depth + 1,
                max_length=max_length,
            )
        return redacted
    if isinstance(payload, (list, tuple, set)):
        return [
            redact_metadata(item, parent_key=parent_key, depth=depth + 1, max_length=max_length)
            for item in list(payload)[:100]
        ]
    return _redact_text(parent_key, str(payload), max_length=max_length)


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("audit"))
    event_type: str
    actor_username: str = "unknown"
    actor_role: str = "unknown"
    workspace_id: str = "default"
    runtime_id: str = "sovereign"
    chat_id: Optional[str] = None
    resource_type: str = "system"
    resource_id: Optional[str] = None
    action: str = "observe"
    result: str = "success"
    trace_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class SecurityEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("sec"))
    event_type: SecurityEventType
    actor_username: str = "unknown"
    actor_role: str = "unknown"
    workspace_id: str = "default"
    runtime_id: str = "sovereign"
    chat_id: Optional[str] = None
    resource_type: str = "system"
    resource_id: Optional[str] = None
    action: str = "detect"
    result: str = "recorded"
    severity: str = "medium"
    trace_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MetricPoint(BaseModel):
    metric_id: str = Field(default_factory=lambda: new_id("metric"))
    metric_name: str
    metric_type: MetricType = "counter"
    value: float = 1.0
    dimensions_json: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)


class TraceRecord(BaseModel):
    trace_id: str = Field(default_factory=lambda: new_id("trace"))
    span_id: str = Field(default_factory=lambda: new_id("span"))
    name: str
    span_kind: str = "internal"
    span_category: str = "chain"
    status: str = "ok"
    latency_ms: Optional[float] = None
    actor_username: str = "unknown"
    workspace_id: str = "default"
    runtime_id: str = "sovereign"
    chat_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    attributes_json: Dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    eval_id: str = Field(default_factory=lambda: new_id("eval"))
    eval_name: str
    status: EvalStatus
    score: float = 0.0
    trace_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    details_json: Dict[str, Any] = Field(default_factory=dict)


class MetricAggregate(BaseModel):
    metric_name: str
    metric_type: MetricType
    count: int = 0
    total: float = 0.0
    avg: float = 0.0
    min: float = 0.0
    max: float = 0.0
    last: float = 0.0


class ObservabilitySummary(BaseModel):
    enabled: bool
    audit_events: int = 0
    security_events: int = 0
    traces: int = 0
    evals: int = 0
    metrics: Dict[str, MetricAggregate] = Field(default_factory=dict)
    legacy_latency_metrics: Dict[str, Any] = Field(default_factory=dict)
    legacy_counter_metrics: Dict[str, Any] = Field(default_factory=dict)
