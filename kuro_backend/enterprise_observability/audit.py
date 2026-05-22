"""SQLite audit store for enterprise observability governance."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from kuro_backend.config import settings
from kuro_backend.enterprise_observability.schemas import (
    AuditEvent,
    EvalResult,
    MetricAggregate,
    MetricPoint,
    SecurityEvent,
    TraceRecord,
    redact_metadata,
    safe_json_dumps,
    safe_json_loads,
)


_WRITE_LOCK = threading.RLock()


def default_db_path() -> Path:
    configured = os.getenv("KURO_ENTERPRISE_OBSERVABILITY_DB_PATH", "").strip()
    if configured:
        return Path(configured)
    working_dir = str(getattr(settings, "WORKING_DIR", "") or os.getcwd())
    return Path(working_dir) / "kuro_enterprise_observability.db"


class EnterpriseObservabilityStore:
    """Small local store for admin-only observability summaries."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with _WRITE_LOCK, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS enterprise_audit_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    actor_username TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    chat_id TEXT,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    trace_id TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_enterprise_audit_created
                    ON enterprise_audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_enterprise_audit_trace
                    ON enterprise_audit_events(trace_id);

                CREATE TABLE IF NOT EXISTS enterprise_security_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    actor_username TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    chat_id TEXT,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    trace_id TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_enterprise_security_created
                    ON enterprise_security_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_enterprise_security_type
                    ON enterprise_security_events(event_type, created_at DESC);

                CREATE TABLE IF NOT EXISTS enterprise_metrics (
                    metric_id TEXT PRIMARY KEY,
                    metric_name TEXT NOT NULL,
                    metric_type TEXT NOT NULL,
                    value REAL NOT NULL,
                    dimensions_json TEXT NOT NULL,
                    trace_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_enterprise_metrics_name
                    ON enterprise_metrics(metric_name, created_at DESC);

                CREATE TABLE IF NOT EXISTS enterprise_traces (
                    trace_id TEXT NOT NULL,
                    span_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    span_kind TEXT NOT NULL,
                    span_category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms REAL,
                    actor_username TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    chat_id TEXT,
                    created_at TEXT NOT NULL,
                    attributes_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_enterprise_traces_created
                    ON enterprise_traces(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_enterprise_traces_trace
                    ON enterprise_traces(trace_id);

                CREATE TABLE IF NOT EXISTS enterprise_evals (
                    eval_id TEXT PRIMARY KEY,
                    eval_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL,
                    trace_id TEXT,
                    created_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_enterprise_evals_created
                    ON enterprise_evals(created_at DESC);
                """
            )

    def record_audit_event(self, event: AuditEvent) -> AuditEvent:
        sanitized = event.model_copy(
            update={"metadata_json": redact_metadata(event.metadata_json)}
        )
        with _WRITE_LOCK, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO enterprise_audit_events (
                    event_id, event_type, actor_username, actor_role, workspace_id,
                    runtime_id, chat_id, resource_type, resource_id, action, result,
                    trace_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sanitized.event_id,
                    sanitized.event_type,
                    sanitized.actor_username,
                    sanitized.actor_role,
                    sanitized.workspace_id,
                    sanitized.runtime_id,
                    sanitized.chat_id,
                    sanitized.resource_type,
                    sanitized.resource_id,
                    sanitized.action,
                    sanitized.result,
                    sanitized.trace_id,
                    sanitized.created_at,
                    safe_json_dumps(sanitized.metadata_json),
                ),
            )
        return sanitized

    def record_security_event(self, event: SecurityEvent) -> SecurityEvent:
        sanitized = event.model_copy(
            update={"metadata_json": redact_metadata(event.metadata_json)}
        )
        with _WRITE_LOCK, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO enterprise_security_events (
                    event_id, event_type, actor_username, actor_role, workspace_id,
                    runtime_id, chat_id, resource_type, resource_id, action, result,
                    severity, trace_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sanitized.event_id,
                    sanitized.event_type,
                    sanitized.actor_username,
                    sanitized.actor_role,
                    sanitized.workspace_id,
                    sanitized.runtime_id,
                    sanitized.chat_id,
                    sanitized.resource_type,
                    sanitized.resource_id,
                    sanitized.action,
                    sanitized.result,
                    sanitized.severity,
                    sanitized.trace_id,
                    sanitized.created_at,
                    safe_json_dumps(sanitized.metadata_json),
                ),
            )
        self.record_audit_event(
            AuditEvent(
                event_id=sanitized.event_id.replace("sec_", "audit_", 1),
                event_type=f"security.{sanitized.event_type}",
                actor_username=sanitized.actor_username,
                actor_role=sanitized.actor_role,
                workspace_id=sanitized.workspace_id,
                runtime_id=sanitized.runtime_id,
                chat_id=sanitized.chat_id,
                resource_type=sanitized.resource_type,
                resource_id=sanitized.resource_id,
                action=sanitized.action,
                result=sanitized.result,
                trace_id=sanitized.trace_id,
                created_at=sanitized.created_at,
                metadata_json={"severity": sanitized.severity, **sanitized.metadata_json},
            )
        )
        return sanitized

    def record_metric(self, metric: MetricPoint) -> MetricPoint:
        sanitized = metric.model_copy(
            update={"dimensions_json": redact_metadata(metric.dimensions_json)}
        )
        with _WRITE_LOCK, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO enterprise_metrics (
                    metric_id, metric_name, metric_type, value,
                    dimensions_json, trace_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sanitized.metric_id,
                    sanitized.metric_name,
                    sanitized.metric_type,
                    float(sanitized.value),
                    safe_json_dumps(sanitized.dimensions_json),
                    sanitized.trace_id,
                    sanitized.created_at,
                ),
            )
        return sanitized

    def record_trace(self, trace: TraceRecord) -> TraceRecord:
        sanitized = trace.model_copy(
            update={"attributes_json": redact_metadata(trace.attributes_json)}
        )
        with _WRITE_LOCK, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO enterprise_traces (
                    trace_id, span_id, name, span_kind, span_category, status,
                    latency_ms, actor_username, workspace_id, runtime_id, chat_id,
                    created_at, attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sanitized.trace_id,
                    sanitized.span_id,
                    sanitized.name,
                    sanitized.span_kind,
                    sanitized.span_category,
                    sanitized.status,
                    sanitized.latency_ms,
                    sanitized.actor_username,
                    sanitized.workspace_id,
                    sanitized.runtime_id,
                    sanitized.chat_id,
                    sanitized.created_at,
                    safe_json_dumps(sanitized.attributes_json),
                ),
            )
        return sanitized

    def record_eval(self, result: EvalResult) -> EvalResult:
        sanitized = result.model_copy(
            update={"details_json": redact_metadata(result.details_json)}
        )
        with _WRITE_LOCK, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO enterprise_evals (
                    eval_id, eval_name, status, score, trace_id, created_at,
                    details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sanitized.eval_id,
                    sanitized.eval_name,
                    sanitized.status,
                    float(sanitized.score),
                    sanitized.trace_id,
                    sanitized.created_at,
                    safe_json_dumps(sanitized.details_json),
                ),
            )
        return sanitized

    def list_audit_events(self, *, limit: int = 100) -> list[AuditEvent]:
        rows = self._select_recent("enterprise_audit_events", limit=limit)
        return [self._row_to_audit(row) for row in rows]

    def list_security_events(
        self,
        *,
        limit: int = 100,
        event_type: Optional[str] = None,
    ) -> list[SecurityEvent]:
        params: list[Any] = []
        where = ""
        if event_type:
            where = "WHERE event_type = ?"
            params.append(event_type)
        query = f"""
            SELECT * FROM enterprise_security_events
            {where}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_security(row) for row in rows]

    def list_metrics(self, *, limit: int = 100, prefix: Optional[str] = None) -> list[MetricPoint]:
        params: list[Any] = []
        where = ""
        if prefix:
            where = "WHERE metric_name LIKE ?"
            params.append(f"{prefix}%")
        query = f"""
            SELECT * FROM enterprise_metrics
            {where}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(max(1, min(int(limit), 5000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_metric(row) for row in rows]

    def list_traces(self, *, limit: int = 100) -> list[TraceRecord]:
        rows = self._select_recent("enterprise_traces", limit=limit)
        return [self._row_to_trace(row) for row in rows]

    def list_evals(self, *, limit: int = 100) -> list[EvalResult]:
        rows = self._select_recent("enterprise_evals", limit=limit)
        return [self._row_to_eval(row) for row in rows]

    def metric_rollups(self, *, prefix: Optional[str] = None, limit: int = 5000) -> Dict[str, MetricAggregate]:
        rollups: Dict[str, MetricAggregate] = {}
        for point in reversed(self.list_metrics(limit=limit, prefix=prefix)):
            aggregate = rollups.get(point.metric_name)
            if aggregate is None:
                aggregate = MetricAggregate(
                    metric_name=point.metric_name,
                    metric_type=point.metric_type,
                    count=0,
                    total=0.0,
                    avg=0.0,
                    min=float(point.value),
                    max=float(point.value),
                    last=float(point.value),
                )
                rollups[point.metric_name] = aggregate
            value = float(point.value)
            aggregate.count += 1
            aggregate.total += value
            aggregate.avg = round(aggregate.total / max(1, aggregate.count), 3)
            aggregate.min = min(aggregate.min, value)
            aggregate.max = max(aggregate.max, value)
            aggregate.last = value
        return rollups

    def counts(self) -> Dict[str, int]:
        tables = {
            "audit_events": "enterprise_audit_events",
            "security_events": "enterprise_security_events",
            "traces": "enterprise_traces",
            "evals": "enterprise_evals",
            "metrics": "enterprise_metrics",
        }
        with self._connect() as conn:
            return {
                name: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for name, table in tables.items()
            }

    def _select_recent(self, table: str, *, limit: int) -> Iterable[sqlite3.Row]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            return conn.execute(
                f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()

    def _row_to_audit(self, row: sqlite3.Row) -> AuditEvent:
        data = dict(row)
        data["metadata_json"] = safe_json_loads(data.get("metadata_json"), {})
        return AuditEvent(**data)

    def _row_to_security(self, row: sqlite3.Row) -> SecurityEvent:
        data = dict(row)
        data["metadata_json"] = safe_json_loads(data.get("metadata_json"), {})
        return SecurityEvent(**data)

    def _row_to_metric(self, row: sqlite3.Row) -> MetricPoint:
        data = dict(row)
        data["dimensions_json"] = safe_json_loads(data.get("dimensions_json"), {})
        return MetricPoint(**data)

    def _row_to_trace(self, row: sqlite3.Row) -> TraceRecord:
        data = dict(row)
        data["attributes_json"] = safe_json_loads(data.get("attributes_json"), {})
        return TraceRecord(**data)

    def _row_to_eval(self, row: sqlite3.Row) -> EvalResult:
        data = dict(row)
        data["details_json"] = safe_json_loads(data.get("details_json"), {})
        return EvalResult(**data)
