"""Admin-only enterprise observability dashboard APIs."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, Query

from kuro_backend.config import settings
from kuro_backend.enterprise_observability.audit import EnterpriseObservabilityStore
from kuro_backend.enterprise_observability.evals import EnterpriseEvalRunner
from kuro_backend.enterprise_observability.metrics import EnterpriseMetrics
from kuro_backend.enterprise_observability.schemas import ObservabilitySummary
from kuro_backend.enterprise_observability.security_events import EnterpriseSecurityEvents
from kuro_backend.enterprise_observability.trace_exporter import EnterpriseTraceExporter


def _success(data: Any = None, **extra: Any) -> Dict[str, Any]:
    payload = {"status": "success", "data": data, "error": None}
    payload.update(extra)
    return payload


class EnterpriseObservabilityService:
    def __init__(self, store: Optional[EnterpriseObservabilityStore] = None) -> None:
        self.store = store or EnterpriseObservabilityStore()
        self.metrics = EnterpriseMetrics(self.store)
        self.trace_exporter = EnterpriseTraceExporter(self.store)
        self.security = EnterpriseSecurityEvents(self.store, self.metrics)
        self.evals = EnterpriseEvalRunner(self.store)

    def summary(self) -> ObservabilitySummary:
        counts = self.store.counts()
        legacy_latency: Dict[str, Any] = {}
        legacy_counters: Dict[str, Any] = {}
        try:
            from kuro_backend import observability

            legacy_latency = observability.get_latency_metrics_snapshot()
            legacy_counters = observability.get_counter_metrics_snapshot()
        except Exception:
            legacy_latency = {}
            legacy_counters = {}
        return ObservabilitySummary(
            enabled=bool(getattr(settings, "KURO_ENTERPRISE_OBSERVABILITY_ENABLED", False)),
            audit_events=counts.get("audit_events", 0),
            security_events=counts.get("security_events", 0),
            traces=counts.get("traces", 0),
            evals=counts.get("evals", 0),
            metrics=self.store.metric_rollups(),
            legacy_latency_metrics=legacy_latency,
            legacy_counter_metrics=legacy_counters,
        )

    def traces(self, *, limit: int = 100) -> list[dict]:
        return [trace.model_dump() for trace in self.trace_exporter.list_traces(limit=limit)]

    def security_events(self, *, limit: int = 100, event_type: Optional[str] = None) -> list[dict]:
        return [
            event.model_dump()
            for event in self.store.list_security_events(limit=limit, event_type=event_type)
        ]

    def eval_results(self, *, limit: int = 100, run_smoke: bool = False) -> list[dict]:
        if run_smoke:
            self.evals.run_default_smoke_evals()
        return [result.model_dump() for result in self.evals.list_evals(limit=limit)]

    def market_snapshot(self) -> dict:
        return {
            "metrics": {
                key: value.model_dump()
                for key, value in self.store.metric_rollups(prefix="market.").items()
            },
            "sources": self._market_sources(),
            "telegram_dlq": {
                key: value.model_dump()
                for key, value in self.store.metric_rollups(prefix="telegram.").items()
            },
        }

    def memory_snapshot(self) -> dict:
        return {
            "metrics": {
                key: value.model_dump()
                for key, value in self.store.metric_rollups(prefix="memory.").items()
            },
            "conflicts": self._memory_conflict_snapshot(),
        }

    def _market_sources(self) -> list[dict]:
        try:
            from kuro_backend.market_v2.source_registry import list_sources

            return [source.model_dump() for source in list_sources()]
        except Exception:
            return []

    def _memory_conflict_snapshot(self) -> dict:
        try:
            from kuro_backend.memory_v3.store import MemoryV3Store

            conflicts = MemoryV3Store().list_conflicts(limit=100)
            return {
                "sample_count": len(conflicts),
                "open": sum(1 for row in conflicts if row.get("status") == "open"),
            }
        except Exception:
            return {"sample_count": 0, "open": 0}


def create_enterprise_observability_router(
    *,
    admin_dependency: Callable[..., Dict[str, str]],
    service: Optional[EnterpriseObservabilityService] = None,
) -> APIRouter:
    router = APIRouter()
    service_instance = service

    def _service() -> EnterpriseObservabilityService:
        nonlocal service_instance
        if service_instance is None:
            service_instance = EnterpriseObservabilityService()
        return service_instance

    @router.get("/api/admin/observability/summary")
    async def observability_summary(_admin: Dict[str, str] = Depends(admin_dependency)):
        summary = _service().summary()
        return _success(summary.model_dump())

    @router.get("/api/admin/observability/traces")
    async def observability_traces(
        limit: int = Query(default=100, ge=1, le=500),
        _admin: Dict[str, str] = Depends(admin_dependency),
    ):
        return _success(_service().traces(limit=limit))

    @router.get("/api/admin/observability/security-events")
    async def observability_security_events(
        limit: int = Query(default=100, ge=1, le=500),
        event_type: Optional[str] = Query(default=None),
        _admin: Dict[str, str] = Depends(admin_dependency),
    ):
        return _success(_service().security_events(limit=limit, event_type=event_type))

    @router.get("/api/admin/observability/evals")
    async def observability_evals(
        limit: int = Query(default=100, ge=1, le=500),
        run_smoke: bool = Query(default=False),
        _admin: Dict[str, str] = Depends(admin_dependency),
    ):
        return _success(_service().eval_results(limit=limit, run_smoke=run_smoke))

    @router.get("/api/admin/observability/market")
    async def observability_market(_admin: Dict[str, str] = Depends(admin_dependency)):
        return _success(_service().market_snapshot())

    @router.get("/api/admin/observability/memory")
    async def observability_memory(_admin: Dict[str, str] = Depends(admin_dependency)):
        return _success(_service().memory_snapshot())

    return router
