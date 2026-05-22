"""AI security event recording for enterprise governance."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, cast

from kuro_backend.enterprise_observability.audit import EnterpriseObservabilityStore
from kuro_backend.enterprise_observability.metrics import (
    EnterpriseMetrics,
    enterprise_observability_enabled,
)
from kuro_backend.enterprise_observability.schemas import SecurityEvent, SecurityEventType


logger = logging.getLogger(__name__)

_EVENT_FIELD_KEYS = {
    "actor_username",
    "actor_role",
    "workspace_id",
    "runtime_id",
    "chat_id",
    "resource_type",
    "resource_id",
    "action",
    "result",
    "severity",
    "trace_id",
}


def _split_event_fields(fields: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    event_kwargs: Dict[str, Any] = {}
    metadata = dict(fields.pop("metadata", {}) or {})
    for key in list(fields.keys()):
        if key in _EVENT_FIELD_KEYS:
            event_kwargs[key] = fields.pop(key)
    metadata.update(fields)
    return event_kwargs, metadata


class EnterpriseSecurityEvents:
    def __init__(
        self,
        store: Optional[EnterpriseObservabilityStore] = None,
        metrics: Optional[EnterpriseMetrics] = None,
    ) -> None:
        self.store = store or EnterpriseObservabilityStore()
        self.metrics = metrics or EnterpriseMetrics(self.store)

    def record_event(
        self,
        *,
        event_type: SecurityEventType,
        actor_username: str = "unknown",
        actor_role: str = "unknown",
        workspace_id: str = "default",
        runtime_id: str = "sovereign",
        chat_id: Optional[str] = None,
        resource_type: str = "system",
        resource_id: Optional[str] = None,
        action: str = "detect",
        result: str = "recorded",
        severity: str = "medium",
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SecurityEvent:
        return self.store.record_security_event(
            SecurityEvent(
                event_type=event_type,
                actor_username=actor_username or "unknown",
                actor_role=actor_role or "unknown",
                workspace_id=workspace_id or "default",
                runtime_id=runtime_id or "sovereign",
                chat_id=chat_id,
                resource_type=resource_type or "system",
                resource_id=resource_id,
                action=action or "detect",
                result=result or "recorded",
                severity=severity or "medium",
                trace_id=trace_id,
                metadata_json=metadata or {},
            )
        )

    def record_prompt_injection_detected(self, **fields: Any) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        return self.record_event(
            event_type="prompt_injection_detected",
            severity=event_kwargs.pop("severity", "high"),
            action=event_kwargs.pop("action", "block"),
            result=event_kwargs.pop("result", "detected"),
            metadata=metadata,
            **event_kwargs,
        )

    def record_memory_poisoning_suspected(self, **fields: Any) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        return self.record_event(
            event_type="memory_poisoning_suspected",
            severity=event_kwargs.pop("severity", "high"),
            action=event_kwargs.pop("action", "quarantine"),
            result=event_kwargs.pop("result", "suspected"),
            metadata=metadata,
            **event_kwargs,
        )

    def record_tool_denied(
        self,
        *,
        tool_id: str,
        actor_username: str = "unknown",
        reason: str = "policy_denied",
        trace_id: Optional[str] = None,
        **fields: Any,
    ) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        self.metrics.record_tool_denial(
            tool_id=tool_id,
            username=actor_username,
            reason=reason,
            trace_id=trace_id,
        )
        return self.record_event(
            event_type="tool_denied",
            actor_username=actor_username,
            resource_type="tool",
            resource_id=tool_id,
            action="deny",
            result="blocked",
            severity=event_kwargs.pop("severity", "medium"),
            trace_id=trace_id,
            metadata={"reason": reason, **metadata},
            **event_kwargs,
        )

    def record_excessive_agency_blocked(self, **fields: Any) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        return self.record_event(
            event_type="excessive_agency_blocked",
            action=event_kwargs.pop("action", "block"),
            result=event_kwargs.pop("result", "blocked"),
            severity=event_kwargs.pop("severity", "high"),
            metadata=metadata,
            **event_kwargs,
        )

    def record_sensitive_info_blocked(self, **fields: Any) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        return self.record_event(
            event_type="sensitive_info_blocked",
            action=event_kwargs.pop("action", "block"),
            result=event_kwargs.pop("result", "blocked"),
            severity=event_kwargs.pop("severity", "high"),
            metadata=metadata,
            **event_kwargs,
        )

    def record_cross_runtime_access_attempt(self, **fields: Any) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        return self.record_event(
            event_type="cross_runtime_access_attempt",
            action=event_kwargs.pop("action", "deny"),
            result=event_kwargs.pop("result", "blocked"),
            severity=event_kwargs.pop("severity", "high"),
            metadata=metadata,
            **event_kwargs,
        )

    def record_cross_user_access_attempt(self, **fields: Any) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        return self.record_event(
            event_type="cross_user_access_attempt",
            action=event_kwargs.pop("action", "deny"),
            result=event_kwargs.pop("result", "blocked"),
            severity=event_kwargs.pop("severity", "high"),
            metadata=metadata,
            **event_kwargs,
        )

    def record_provider_error(
        self,
        *,
        provider: str,
        error: str,
        model_alias: str = "",
        fallback_alias: str = "",
        actor_username: str = "unknown",
        trace_id: Optional[str] = None,
        **fields: Any,
    ) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        self.metrics.record_provider_error(
            provider=provider,
            model_alias=model_alias,
            fallback_alias=fallback_alias,
            trace_id=trace_id,
        )
        if fallback_alias:
            self.metrics.record_provider_fallback(
                provider=provider,
                model_alias=model_alias,
                fallback_alias=fallback_alias,
                trace_id=trace_id,
            )
        return self.record_event(
            event_type="provider_error",
            actor_username=actor_username,
            resource_type="provider",
            resource_id=provider,
            action="fallback" if fallback_alias else "record_error",
            result="degraded" if fallback_alias else "error",
            severity=event_kwargs.pop("severity", "medium"),
            trace_id=trace_id,
            metadata={
                "error": error,
                "model_alias": model_alias,
                "fallback_alias": fallback_alias,
                **metadata,
            },
            **event_kwargs,
        )

    def record_schema_validation_failed(
        self,
        *,
        resource_type: str,
        error: str,
        actor_username: str = "unknown",
        trace_id: Optional[str] = None,
        **fields: Any,
    ) -> SecurityEvent:
        event_kwargs, metadata = _split_event_fields(fields)
        self.metrics.record_structured_output_validity(False, resource_type=resource_type)
        return self.record_event(
            event_type="schema_validation_failed",
            actor_username=actor_username,
            resource_type=resource_type,
            action="validate",
            result="failed",
            severity=event_kwargs.pop("severity", "medium"),
            trace_id=trace_id,
            metadata={"error": error, **metadata},
            **event_kwargs,
        )


def record_security_event_if_enabled(event_type: str, **fields: Any) -> Optional[SecurityEvent]:
    if not enterprise_observability_enabled():
        return None
    try:
        return EnterpriseSecurityEvents().record_event(
            event_type=cast(SecurityEventType, event_type),
            **fields,
        )
    except Exception as exc:
        logger.debug("[ENTERPRISE_OBSERVABILITY] security event skipped: %s", exc)
        return None


def record_tool_denied_if_enabled(tool_id: str, **fields: Any) -> Optional[SecurityEvent]:
    if not enterprise_observability_enabled():
        return None
    try:
        return EnterpriseSecurityEvents().record_tool_denied(tool_id=tool_id, **fields)
    except Exception as exc:
        logger.debug("[ENTERPRISE_OBSERVABILITY] tool denial event skipped: %s", exc)
        return None


def record_provider_error_if_enabled(provider: str, error: str, **fields: Any) -> Optional[SecurityEvent]:
    if not enterprise_observability_enabled():
        return None
    try:
        return EnterpriseSecurityEvents().record_provider_error(
            provider=provider,
            error=error,
            **fields,
        )
    except Exception as exc:
        logger.debug("[ENTERPRISE_OBSERVABILITY] provider error event skipped: %s", exc)
        return None
