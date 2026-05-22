"""Enterprise metric helpers with flag-aware global recorders."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from kuro_backend.config import settings
from kuro_backend.enterprise_observability.audit import EnterpriseObservabilityStore
from kuro_backend.enterprise_observability.schemas import MetricPoint


logger = logging.getLogger(__name__)


def enterprise_observability_enabled() -> bool:
    return bool(getattr(settings, "KURO_ENTERPRISE_OBSERVABILITY_ENABLED", False))


class EnterpriseMetrics:
    def __init__(self, store: Optional[EnterpriseObservabilityStore] = None) -> None:
        self.store = store or EnterpriseObservabilityStore()

    def increment(
        self,
        metric_name: str,
        *,
        amount: int = 1,
        dimensions: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> MetricPoint:
        return self.store.record_metric(
            MetricPoint(
                metric_name=metric_name,
                metric_type="counter",
                value=float(amount),
                dimensions_json=dimensions or {},
                trace_id=trace_id,
            )
        )

    def observe_latency(
        self,
        metric_name: str,
        value_ms: float,
        *,
        dimensions: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> MetricPoint:
        return self.store.record_metric(
            MetricPoint(
                metric_name=metric_name,
                metric_type="latency",
                value=float(value_ms),
                dimensions_json=dimensions or {},
                trace_id=trace_id,
            )
        )

    def gauge(
        self,
        metric_name: str,
        value: float,
        *,
        dimensions: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> MetricPoint:
        return self.store.record_metric(
            MetricPoint(
                metric_name=metric_name,
                metric_type="gauge",
                value=float(value),
                dimensions_json=dimensions or {},
                trace_id=trace_id,
            )
        )

    def record_chat_latency(self, latency_ms: float, **dimensions: Any) -> MetricPoint:
        return self.observe_latency("chat.latency_ms", latency_ms, dimensions=dimensions)

    def record_provider_latency(self, latency_ms: float, **dimensions: Any) -> MetricPoint:
        return self.observe_latency("provider.latency_ms", latency_ms, dimensions=dimensions)

    def record_provider_error(self, **dimensions: Any) -> MetricPoint:
        return self.increment("provider.errors", dimensions=dimensions)

    def record_provider_fallback(self, **dimensions: Any) -> MetricPoint:
        return self.increment("provider.fallbacks", dimensions=dimensions)

    def record_token_usage(
        self,
        *,
        total_tokens: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        **dimensions: Any,
    ) -> MetricPoint:
        payload = {
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            **dimensions,
        }
        return self.increment("token.usage", amount=int(total_tokens or 0), dimensions=payload)

    def record_memory_retrieval_latency(self, latency_ms: float, **dimensions: Any) -> MetricPoint:
        return self.observe_latency("memory.retrieval_latency_ms", latency_ms, dimensions=dimensions)

    def record_memory_write_latency(self, latency_ms: float, **dimensions: Any) -> MetricPoint:
        return self.observe_latency("memory.write_latency_ms", latency_ms, dimensions=dimensions)

    def record_memory_conflict(self, *, amount: int = 1, **dimensions: Any) -> MetricPoint:
        return self.increment("memory.conflicts", amount=amount, dimensions=dimensions)

    def record_tool_call(self, **dimensions: Any) -> MetricPoint:
        return self.increment("tool.calls", dimensions=dimensions)

    def record_tool_denial(self, **dimensions: Any) -> MetricPoint:
        return self.increment("tool.denials", dimensions=dimensions)

    def record_market_freshness(self, freshness_seconds: float, **dimensions: Any) -> MetricPoint:
        return self.gauge(
            "market.source_freshness_seconds",
            float(freshness_seconds),
            dimensions=dimensions,
        )

    def record_telegram_dlq(self, *, amount: int = 1, **dimensions: Any) -> MetricPoint:
        return self.increment("telegram.dlq", amount=amount, dimensions=dimensions)

    def record_sse_disconnect(self, **dimensions: Any) -> MetricPoint:
        return self.increment("sse.disconnects", dimensions=dimensions)

    def record_structured_output_validity(self, valid: bool, **dimensions: Any) -> MetricPoint:
        return self.gauge("structured_output.validity", 1.0 if valid else 0.0, dimensions=dimensions)

    def record_eval_score(self, score: float, **dimensions: Any) -> MetricPoint:
        return self.gauge("eval.hallucination_score", float(score), dimensions=dimensions)


def _record_if_enabled(method_name: str, *args: Any, **kwargs: Any) -> Optional[MetricPoint]:
    if not enterprise_observability_enabled():
        return None
    try:
        metrics = EnterpriseMetrics()
        method = getattr(metrics, method_name)
        return method(*args, **kwargs)
    except Exception as exc:
        logger.debug("[ENTERPRISE_OBSERVABILITY] metric %s skipped: %s", method_name, exc)
        return None


def record_chat_latency_if_enabled(latency_ms: float, **dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_chat_latency", latency_ms, **dimensions)


def record_provider_latency_if_enabled(latency_ms: float, **dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_provider_latency", latency_ms, **dimensions)


def record_provider_error_if_enabled(**dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_provider_error", **dimensions)


def record_provider_fallback_if_enabled(**dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_provider_fallback", **dimensions)


def record_token_usage_if_enabled(
    *,
    total_tokens: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    **dimensions: Any,
) -> Optional[MetricPoint]:
    return _record_if_enabled(
        "record_token_usage",
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        **dimensions,
    )


def record_memory_retrieval_latency_if_enabled(latency_ms: float, **dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_memory_retrieval_latency", latency_ms, **dimensions)


def record_memory_write_latency_if_enabled(latency_ms: float, **dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_memory_write_latency", latency_ms, **dimensions)


def record_memory_conflict_if_enabled(*, amount: int = 1, **dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_memory_conflict", amount=amount, **dimensions)


def record_tool_call_if_enabled(**dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_tool_call", **dimensions)


def record_tool_denial_if_enabled(**dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_tool_denial", **dimensions)


def record_sse_disconnect_if_enabled(**dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_sse_disconnect", **dimensions)


def record_market_freshness_if_enabled(freshness_seconds: float, **dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_market_freshness", freshness_seconds, **dimensions)


def record_telegram_dlq_if_enabled(*, amount: int = 1, **dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_telegram_dlq", amount=amount, **dimensions)


def record_structured_output_validity_if_enabled(valid: bool, **dimensions: Any) -> Optional[MetricPoint]:
    return _record_if_enabled("record_structured_output_validity", valid, **dimensions)
