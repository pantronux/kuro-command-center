"""
Playground DB layer.

--- Header Doc ---
Purpose: Bootstrap and CRUD for isolated kuro_playground.db.
Caller: KPR runtime service, API, tests.
Dependencies: sqlite3, json, hashlib, migration SQL.
Main Functions: init_db() and insert/query helpers.
Side Effects: Creates and writes KPR database file.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from playground_runtime.errors import PlaygroundIsolationError
from playground_runtime.governance.boundary_validator import validate_db_path
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace
from playground_runtime.schema.evidence_artifact import EvidenceArtifact
from playground_runtime.telemetry.event_schema import TelemetryEvent


class PlaygroundDB:
    def __init__(self, db_path: str):
        validate_db_path(db_path)
        self.db_path = Path(db_path)
        self._init_done = False

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def init_db(self) -> None:
        if self._init_done:
            return
        migration = Path(__file__).resolve().parent / "migrations" / "001_initial_schema.sql"
        sql = migration.read_text(encoding="utf-8")
        conn = self._conn()
        try:
            conn.executescript(sql)
            conn.commit()
        finally:
            conn.close()
        self._init_done = True

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _insert(self, sql: str, values: tuple) -> None:
        self.init_db()
        conn = self._conn()
        try:
            conn.execute(sql, values)
            conn.commit()
        finally:
            conn.close()

    def create_session(self, mode: str, runtime_config_hash: str) -> str:
        sid = str(uuid4())
        self._insert(
            "INSERT INTO playground_sessions(id, mode, status, created_at_utc, runtime_config_hash) VALUES (?, ?, 'active', ?, ?)",
            (sid, mode, self._now(), runtime_config_hash),
        )
        return sid

    def create_session_with_id(self, session_id: str, mode: str, runtime_config_hash: str) -> str:
        self._insert(
            "INSERT INTO playground_sessions(id, mode, status, created_at_utc, runtime_config_hash) VALUES (?, ?, 'active', ?, ?)",
            (session_id, mode, self._now(), runtime_config_hash),
        )
        return session_id

    def insert_runtime_config(self, session_id: str, config: dict) -> str:
        rid = str(uuid4())
        self._insert(
            "INSERT INTO runtime_configs(id, session_id, config_json, created_at_utc) VALUES (?, ?, ?, ?)",
            (rid, session_id, json.dumps(config, ensure_ascii=False), self._now()),
        )
        return rid

    def insert_feature_flag_snapshot(self, session_id: str, snapshot: dict) -> str:
        fid = str(uuid4())
        self._insert(
            "INSERT INTO feature_flag_snapshots(id, session_id, snapshot_json, created_at_utc) VALUES (?, ?, ?, ?)",
            (fid, session_id, json.dumps(snapshot, ensure_ascii=False), self._now()),
        )
        return fid

    def insert_provider_metadata(self, provider_id: str, model_version: str, endpoint: str | None, capability_hash: str | None, metadata: dict) -> str:
        mid = str(uuid4())
        self._insert(
            "INSERT INTO provider_metadata(id, provider_id, model_version, endpoint, capability_hash, metadata_json, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, provider_id, model_version, endpoint, capability_hash, json.dumps(metadata, ensure_ascii=False), self._now()),
        )
        return mid

    def insert_model_execution(self, session_id: str, provider_id: str, model_id: str, model_version: str, request_id: str, prompt_sha256: str, dataset_version: str | None, latency_ms: float | None, input_tokens: int | None, output_tokens: int | None, total_tokens: int | None, finish_reason: str | None) -> str:
        eid = str(uuid4())
        self._insert(
            """
            INSERT INTO model_executions(id, session_id, provider_id, model_id, model_version, request_id, prompt_sha256, dataset_version, latency_ms, input_tokens, output_tokens, total_tokens, finish_reason, created_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eid, session_id, provider_id, model_id, model_version, request_id, prompt_sha256, dataset_version, latency_ms, input_tokens, output_tokens, total_tokens, finish_reason, self._now()),
        )
        return eid

    def insert_raw_evidence(self, session_id: str, execution_id: str, artifact: EvidenceArtifact) -> str:
        rid = str(uuid4())
        raw_json = json.dumps(artifact.raw_json, ensure_ascii=False)
        raw_hash = sha256(raw_json.encode("utf-8")).hexdigest()
        self._insert(
            """
            INSERT INTO raw_evidence(id, session_id, execution_id, provider_id, model_version, response_schema_version, request_id, prompt_sha256, dataset_version, collected_at_utc, raw_json, raw_sha256, created_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                session_id,
                execution_id,
                artifact.provider_id,
                artifact.model_version,
                artifact.response_schema_version,
                artifact.request_id,
                artifact.prompt_sha256,
                artifact.dataset_version,
                artifact.collected_at_utc.isoformat(),
                raw_json,
                raw_hash,
                self._now(),
            ),
        )
        return rid

    def insert_canonical_trace(self, trace: CanonicalInferenceTrace) -> str:
        self._insert(
            """
            INSERT INTO canonical_traces(id, session_id, execution_id, provider_id, model_id, model_version, schema_version, prompt_sha256, dataset_version, collected_at_utc, response_text, finish_reason, input_tokens, output_tokens, total_tokens, latency_ms, grounding_chunks_json, citation_objects_json, safety_ratings_json, provider_raw_id, forensic_flags_json, normalization_warnings_json, extra_fields_json, created_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace.trace_id,
                trace.session_id,
                trace.execution_id,
                trace.provider_id,
                trace.model_id,
                trace.model_version,
                trace.schema_version,
                trace.prompt_sha256,
                trace.dataset_version,
                trace.collected_at_utc.isoformat(),
                trace.response_text,
                trace.finish_reason,
                trace.input_tokens,
                trace.output_tokens,
                trace.total_tokens,
                trace.latency_ms,
                json.dumps(trace.grounding_chunks, ensure_ascii=False),
                json.dumps(trace.citation_objects, ensure_ascii=False),
                json.dumps(trace.safety_ratings, ensure_ascii=False) if trace.safety_ratings is not None else None,
                trace.provider_raw_id,
                json.dumps(trace.forensic_flags, ensure_ascii=False),
                json.dumps(trace.normalization_warnings, ensure_ascii=False),
                json.dumps(trace.extra_fields, ensure_ascii=False),
                self._now(),
            ),
        )
        return trace.trace_id

    def insert_telemetry_event(self, event: TelemetryEvent) -> str:
        tid = str(uuid4())
        self._insert(
            "INSERT INTO telemetry_events(id, session_id, execution_id, provider_id, event_type, payload_json, timestamp_utc, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tid,
                event.session_id,
                event.execution_id,
                event.provider_id,
                event.event_type,
                json.dumps(event.payload, ensure_ascii=False),
                event.timestamp_utc.isoformat(),
                self._now(),
            ),
        )
        return tid

    def insert_hallucination_record(self, session_id: str, execution_id: str, trace_id: str, risk_score: float, flags: list[str], evidence: dict) -> str:
        hid = str(uuid4())
        self._insert(
            "INSERT INTO hallucination_records(id, session_id, execution_id, trace_id, risk_score, flags_json, evidence_json, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (hid, session_id, execution_id, trace_id, risk_score, json.dumps(flags), json.dumps(evidence), self._now()),
        )
        return hid

    def insert_epistemic_diff(self, session_id: str, prompt_sha256: str, left_trace_id: str, right_trace_id: str, divergence_score: float, payload: dict) -> str:
        did = str(uuid4())
        self._insert(
            "INSERT INTO epistemic_diffs(id, session_id, prompt_sha256, left_trace_id, right_trace_id, divergence_score, diff_json, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (did, session_id, prompt_sha256, left_trace_id, right_trace_id, divergence_score, json.dumps(payload), self._now()),
        )
        return did

    def insert_ontology_mapping(self, session_id: str, trace_id: str, node_id: str, node_label: str, edges: list[dict]) -> str:
        oid = str(uuid4())
        self._insert(
            "INSERT INTO ontology_mappings(id, session_id, trace_id, node_id, node_label, edges_json, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (oid, session_id, trace_id, node_id, node_label, json.dumps(edges), self._now()),
        )
        return oid

    def insert_ontology_graph(self, session_id: str, graph_version: str, graph_jsonld: str | None, graph_rdf_star: str | None, alignment_score: float | None) -> str:
        gid = str(uuid4())
        self._insert(
            "INSERT INTO ontology_graphs(id, session_id, graph_version, graph_jsonld, graph_rdf_star, alignment_score, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gid, session_id, graph_version, graph_jsonld, graph_rdf_star, alignment_score, self._now()),
        )
        return gid

    def insert_reproducibility_record(self, session_id: str, execution_id: str | None, prompt_sha256: str, dataset_version: str | None, seed: str | None, execution_fingerprint: str) -> str:
        rid = str(uuid4())
        self._insert(
            "INSERT INTO reproducibility_records(id, session_id, execution_id, prompt_sha256, dataset_version, seed, execution_fingerprint, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, session_id, execution_id, prompt_sha256, dataset_version, seed, execution_fingerprint, self._now()),
        )
        return rid

    def insert_forensic_report(self, session_id: str, report_format: str, report_body: str, reproducibility_record_id: str | None, artifact_path: str | None) -> str:
        fid = str(uuid4())
        self._insert(
            "INSERT INTO forensic_reports(id, session_id, report_format, report_body, reproducibility_record_id, artifact_path, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fid, session_id, report_format, report_body, reproducibility_record_id, artifact_path, self._now()),
        )
        return fid

    def list_canonical_traces(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM canonical_traces WHERE session_id=? ORDER BY created_at_utc ASC", (session_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_raw_evidence(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM raw_evidence WHERE session_id=? ORDER BY created_at_utc ASC", (session_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_session(self, session_id: str) -> dict | None:
        self.init_db()
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM playground_sessions WHERE id=?", (session_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_sessions(self, limit: int = 20, mode: str | None = None) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            if mode:
                rows = conn.execute(
                    "SELECT * FROM playground_sessions WHERE mode=? ORDER BY created_at_utc DESC LIMIT ?",
                    (mode, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM playground_sessions ORDER BY created_at_utc DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_latest_session(self) -> dict | None:
        rows = self.list_sessions(limit=1)
        if not rows:
            return None
        return rows[0]

    def list_model_executions(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM model_executions WHERE session_id=? ORDER BY created_at_utc ASC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_session_executions(self, session_id: str) -> list[dict]:
        return self.list_model_executions(session_id=session_id)

    def get_model_execution(self, execution_id: str) -> dict | None:
        self.init_db()
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM model_executions WHERE id=?", (execution_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_raw_evidence_by_execution(self, execution_id: str) -> dict | None:
        self.init_db()
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM raw_evidence WHERE execution_id=? ORDER BY created_at_utc DESC LIMIT 1",
                (execution_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_canonical_trace_by_execution(self, execution_id: str) -> dict | None:
        self.init_db()
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM canonical_traces WHERE execution_id=? ORDER BY created_at_utc DESC LIMIT 1",
                (execution_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_epistemic_diffs(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM epistemic_diffs WHERE session_id=? ORDER BY created_at_utc DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_ontology_graphs(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM ontology_graphs WHERE session_id=? ORDER BY created_at_utc DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_reproducibility_records(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM reproducibility_records WHERE session_id=? ORDER BY created_at_utc DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_forensic_reports(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM forensic_reports WHERE session_id=? ORDER BY created_at_utc DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_runtime_configs(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM runtime_configs WHERE session_id=? ORDER BY created_at_utc DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_feature_flag_snapshots(self, session_id: str) -> list[dict]:
        self.init_db()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM feature_flag_snapshots WHERE session_id=? ORDER BY created_at_utc DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def purge_expired_evidence(self, retention_days: int) -> int:
        """
        Skeleton for future evidence retention lifecycle.

        Current behavior is intentionally non-destructive. Deletion logic is
        deferred because raw_evidence currently has immutability triggers.
        """
        self.init_db()
        if retention_days <= 0:
            return 0
        return 0

    def assert_only_playground_db(self) -> None:
        self.init_db()
        conn = self._conn()
        try:
            dbs = conn.execute("PRAGMA database_list").fetchall()
            for row in dbs:
                db_name = Path(row[2]).name
                if db_name in {"kuro_short_term.db", "kuro_chat_history.db", "kuro_intelligence.db"}:
                    raise PlaygroundIsolationError("BOUNDARY_VIOLATION: production DB attached")
        finally:
            conn.close()
