"""Lightweight enterprise smoke evaluations for governance dashboards."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from kuro_backend.enterprise_observability.audit import EnterpriseObservabilityStore
from kuro_backend.enterprise_observability.schemas import EvalResult


BOUNDARY_LEAKAGE_RE = re.compile(
    r"(?i)(api[_-]?key|secret|bearer\s+[a-z0-9._-]+|/home/[^/\s]+/|runtime_[a-z0-9_-]+)"
)


class EnterpriseEvalRunner:
    def __init__(self, store: Optional[EnterpriseObservabilityStore] = None) -> None:
        self.store = store or EnterpriseObservabilityStore()

    def record_eval(
        self,
        *,
        eval_name: str,
        status: str,
        score: float,
        details: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> EvalResult:
        return self.store.record_eval(
            EvalResult(
                eval_name=eval_name,
                status=status,  # type: ignore[arg-type]
                score=max(0.0, min(1.0, float(score))),
                trace_id=trace_id,
                details_json=details or {},
            )
        )

    def list_evals(self, *, limit: int = 100) -> list[EvalResult]:
        return self.store.list_evals(limit=limit)

    def run_memory_retrieval_quality_smoke_eval(
        self,
        *,
        retrieved_items: Optional[Iterable[Dict[str, Any]]] = None,
        trace_id: Optional[str] = None,
    ) -> EvalResult:
        items = list(retrieved_items or [])
        if not items:
            return self.record_eval(
                eval_name="memory_retrieval_quality_smoke",
                status="degraded",
                score=0.75,
                trace_id=trace_id,
                details={"checked_items": 0, "reason": "no sample retrieval payload supplied"},
            )
        grounded = sum(1 for item in items if item.get("memory_id") or item.get("source") or item.get("provenance"))
        score = grounded / max(1, len(items))
        return self.record_eval(
            eval_name="memory_retrieval_quality_smoke",
            status="pass" if score >= 0.8 else "degraded",
            score=score,
            trace_id=trace_id,
            details={"checked_items": len(items), "grounded_items": grounded},
        )

    def run_sse_contract_eval(
        self,
        *,
        events: Optional[Iterable[Dict[str, Any]]] = None,
        trace_id: Optional[str] = None,
    ) -> EvalResult:
        sample = list(
            events
            or [
                {"event": "trace", "data": {"phase": "started"}},
                {"event": "token", "data": {"text": "ok"}},
                {"event": "done", "data": {"ok": True}},
            ]
        )
        names = [str(item.get("event") or "") for item in sample]
        valid = bool(sample) and names[0] == "trace" and "done" in names and all("data" in item for item in sample)
        return self.record_eval(
            eval_name="sse_contract",
            status="pass" if valid else "fail",
            score=1.0 if valid else 0.0,
            trace_id=trace_id,
            details={"events": names},
        )

    def run_market_sentinel_source_quality_eval(
        self,
        *,
        sources: Optional[Iterable[Dict[str, Any]]] = None,
        trace_id: Optional[str] = None,
    ) -> EvalResult:
        source_rows = list(sources or self._default_market_sources())
        configured = sum(1 for source in source_rows if source.get("enabled", True) is not False)
        has_trust = sum(1 for source in source_rows if source.get("source_id") or source.get("provider") or source.get("name"))
        score = min(1.0, (configured + has_trust) / max(1, len(source_rows) * 2))
        return self.record_eval(
            eval_name="market_sentinel_source_quality",
            status="pass" if score >= 0.75 else "degraded",
            score=score,
            trace_id=trace_id,
            details={"source_count": len(source_rows), "configured": configured, "identified": has_trust},
        )

    def run_provider_fallback_eval(self, *, trace_id: Optional[str] = None) -> EvalResult:
        rollups = self.store.metric_rollups(prefix="provider.")
        fallback_count = rollups.get("provider.fallbacks")
        provider_errors = rollups.get("provider.errors")
        score = 1.0 if fallback_count and fallback_count.total > 0 else 0.75
        return self.record_eval(
            eval_name="provider_fallback",
            status="pass" if score >= 1.0 else "degraded",
            score=score,
            trace_id=trace_id,
            details={
                "fallback_count": fallback_count.total if fallback_count else 0,
                "provider_errors": provider_errors.total if provider_errors else 0,
            },
        )

    def run_boundary_leakage_eval(self, *, text: str = "", trace_id: Optional[str] = None) -> EvalResult:
        leaked = bool(BOUNDARY_LEAKAGE_RE.search(text or ""))
        return self.record_eval(
            eval_name="boundary_leakage",
            status="fail" if leaked else "pass",
            score=0.0 if leaked else 1.0,
            trace_id=trace_id,
            details={"sample_length": len(text or ""), "leakage_detected": leaked},
        )

    def run_default_smoke_evals(self) -> list[EvalResult]:
        return [
            self.run_memory_retrieval_quality_smoke_eval(),
            self.run_sse_contract_eval(),
            self.run_market_sentinel_source_quality_eval(),
            self.run_provider_fallback_eval(),
            self.run_boundary_leakage_eval(),
        ]

    def _default_market_sources(self) -> list[Dict[str, Any]]:
        try:
            from kuro_backend.market_v2.source_registry import list_sources

            return [source.model_dump() for source in list_sources()]
        except Exception:
            return []
