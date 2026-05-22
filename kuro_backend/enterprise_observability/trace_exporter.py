"""Redacted trace export helpers for enterprise observability."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from kuro_backend.enterprise_observability.audit import EnterpriseObservabilityStore
from kuro_backend.enterprise_observability.metrics import enterprise_observability_enabled
from kuro_backend.enterprise_observability.schemas import TraceRecord, redact_metadata


logger = logging.getLogger(__name__)


OPENINFERENCE_CATEGORY_BY_KIND = {
    "llm": "LLM",
    "provider": "LLM",
    "retriever": "RETRIEVER",
    "memory": "RETRIEVER",
    "tool": "TOOL",
    "chain": "CHAIN",
    "agent": "AGENT",
}


class EnterpriseTraceExporter:
    def __init__(self, store: Optional[EnterpriseObservabilityStore] = None) -> None:
        self.store = store or EnterpriseObservabilityStore()

    def record_trace(
        self,
        *,
        name: str,
        trace_id: Optional[str] = None,
        span_kind: str = "internal",
        span_category: str = "chain",
        status: str = "ok",
        latency_ms: Optional[float] = None,
        actor_username: str = "unknown",
        workspace_id: str = "default",
        runtime_id: str = "sovereign",
        chat_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> TraceRecord:
        normalized_attrs = self._normalize_attributes(
            name=name,
            span_kind=span_kind,
            span_category=span_category,
            attributes=attributes or {},
        )
        trace_value = trace_id or normalized_attrs.get("trace_id")
        trace_kwargs: Dict[str, Any] = {}
        if trace_value:
            trace_kwargs["trace_id"] = str(trace_value)
        return self.store.record_trace(
            TraceRecord(
                name=name,
                span_kind=span_kind,
                span_category=normalized_attrs.get("openinference.span.kind", span_category),
                status=status,
                latency_ms=latency_ms,
                actor_username=actor_username or "unknown",
                workspace_id=workspace_id or "default",
                runtime_id=runtime_id or "sovereign",
                chat_id=chat_id,
                attributes_json=redact_metadata(normalized_attrs),
                **trace_kwargs,
            )
        )

    def list_traces(self, *, limit: int = 100) -> list[TraceRecord]:
        return self.store.list_traces(limit=limit)

    def _normalize_attributes(
        self,
        *,
        name: str,
        span_kind: str,
        span_category: str,
        attributes: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized: Dict[str, Any] = dict(attributes or {})
        lower_kind = str(span_category or span_kind or "").lower()
        oi_kind = normalized.get("openinference.span.kind") or OPENINFERENCE_CATEGORY_BY_KIND.get(
            lower_kind,
            str(span_category or "CHAIN").upper(),
        )
        normalized["openinference.span.kind"] = oi_kind
        normalized.setdefault("kuro.span.name", name)
        normalized.setdefault("kuro.span.kind", span_kind)
        normalized.setdefault("kuro.span.category", span_category)

        provider = (
            normalized.get("provider")
            or normalized.get("provider_id")
            or normalized.get("gen_ai.system")
        )
        model = (
            normalized.get("model")
            or normalized.get("model_id")
            or normalized.get("model_alias")
            or normalized.get("gen_ai.request.model")
        )
        if provider:
            normalized.setdefault("gen_ai.system", str(provider))
        if model:
            normalized.setdefault("gen_ai.request.model", str(model))
        if oi_kind in {"LLM", "AGENT", "CHAIN"}:
            normalized.setdefault("gen_ai.operation.name", "chat")
        return normalized


def record_trace_if_enabled(**fields: Any) -> Optional[TraceRecord]:
    if not enterprise_observability_enabled():
        return None
    try:
        return EnterpriseTraceExporter().record_trace(**fields)
    except Exception as exc:
        logger.debug("[ENTERPRISE_OBSERVABILITY] trace export skipped: %s", exc)
        return None
