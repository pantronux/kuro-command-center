"""
Playground runtime orchestration service.

--- Header Doc ---
Purpose: Coordinate KPR execution flow from provider dispatch to forensic persistence.
Caller: playground API router.
Dependencies: KPR db/providers/schema/telemetry/forensic/ontology/export modules.
Main Functions: create_session(), execute_single(), execute_comparative(), reconstruct_ontology(), build_and_export_report().
Side Effects: Writes to kuro_playground.db and optional telemetry/export outputs.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional

from playground_runtime.config import PlaygroundSettings, get_settings
from playground_runtime.db.playground_db import PlaygroundDB
from playground_runtime.errors import PlaygroundError, ProviderExecutionError
from playground_runtime.evaluation.report_builder import build_report
from playground_runtime.export.report_exporter import ReportExporter
from playground_runtime.forensic.epistemic_diff import compute_epistemic_diff
from playground_runtime.forensic.evidence_store import EvidenceStore
from playground_runtime.forensic.hallucination_analyzer import analyze_trace
from playground_runtime.governance.boundary_validator import validate_playground_imports
from playground_runtime.governance.isolation_gate import IsolationGate
from playground_runtime.modes import resolve_mode_profile
from playground_runtime.ontology.graph_exporter import export_jsonld, export_rdf_star
from playground_runtime.ontology.reconstructor import reconstruct_ontology_graph
from playground_runtime.providers.adapters.base_adapter import ProviderRequest, ProviderResponse
from playground_runtime.providers.registry import ProviderRegistry
from playground_runtime.providers.router import ProviderRouter
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace
from playground_runtime.schema.evidence_artifact import EvidenceArtifact
from playground_runtime.schema.normalization_registry import NormalizationRegistry
from playground_runtime.telemetry.collector import TelemetryCollector
from playground_runtime.telemetry.otel_bridge import PlaygroundOtelBridge


class PlaygroundRuntimeService:
    _SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,80}$")

    def __init__(self, settings: Optional[PlaygroundSettings] = None):
        self.settings = settings or get_settings()
        validate_playground_imports()

        self.db = PlaygroundDB(self.settings.KURO_PLAYGROUND_DB_PATH)
        self.db.init_db()
        self.gate = IsolationGate(playground_db_path=Path(self.settings.KURO_PLAYGROUND_DB_PATH))
        self.gate.enforce(references=[self.db, self.settings])

        self.registry = ProviderRegistry(self.settings)
        self.registry.load_from_env()
        self.router = ProviderRouter(
            self.registry,
            max_concurrent=self.settings.KURO_PLAYGROUND_MAX_CONCURRENT_PROVIDERS,
        )
        self.normalization = NormalizationRegistry()
        self.evidence_store = EvidenceStore(self.db)
        self.report_exporter = ReportExporter()

        self.telemetry: Optional[TelemetryCollector] = None
        if self.settings.KURO_PLAYGROUND_TELEMETRY_ENABLED:
            otel = PlaygroundOtelBridge(
                endpoint=self.settings.KURO_PLAYGROUND_OTEL_ENDPOINT,
                project_name=self.settings.KURO_PLAYGROUND_OTEL_PROJECT_NAME,
                service_name=self.settings.KURO_PLAYGROUND_OTEL_SERVICE_NAME,
            )
            self.telemetry = TelemetryCollector(db=self.db, otel=otel)

    def assert_api_enabled(self) -> None:
        if not self.settings.KURO_PLAYGROUND_ENABLED or not self.settings.KURO_PLAYGROUND_API_ENABLED:
            raise PermissionError("KPR API disabled by feature flag")

    def health(self) -> dict:
        return {
            "enabled": self.settings.KURO_PLAYGROUND_ENABLED,
            "api_enabled": self.settings.KURO_PLAYGROUND_API_ENABLED,
            "active_providers": self.registry.list_active(),
            "provider_health": self.registry.health_check(),
            "db_path": self.settings.KURO_PLAYGROUND_DB_PATH,
        }

    def list_providers(self) -> list[dict]:
        rows = []
        health = self.registry.health_check()
        for provider_id in self.registry.list_active():
            cap = self.registry.get_capability_spec(provider_id)
            rows.append(
                {
                    "provider_id": provider_id,
                    "healthy": health.get(provider_id, False),
                    "capability_spec": asdict(cap),
                }
            )
        return rows

    def create_session(
        self,
        mode: str,
        runtime_config_override: Optional[dict] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        profile = resolve_mode_profile(mode)
        if session_id:
            if not self._SESSION_ID_PATTERN.fullmatch(session_id):
                raise PlaygroundError("invalid session_id format (allowed: A-Za-z0-9._:-, length 3-80)")
            existing = self.db.get_session(session_id)
            if existing:
                return {
                    "session_id": existing["id"],
                    "mode": existing["mode"],
                    "runtime_config_hash": existing.get("runtime_config_hash"),
                    "reconnected": True,
                    "created_at_utc": existing["created_at_utc"],
                    "status": existing.get("status", "active"),
                }

        runtime_config = {
            "mode": profile.name,
            "profile": asdict(profile),
            "flags": self.settings.snapshot_flags(),
        }
        if runtime_config_override:
            runtime_config["override"] = runtime_config_override
        runtime_hash = sha256(
            json.dumps(runtime_config, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        sid = (
            self.db.create_session_with_id(session_id=session_id, mode=profile.name, runtime_config_hash=runtime_hash)
            if session_id
            else self.db.create_session(mode=profile.name, runtime_config_hash=runtime_hash)
        )
        self.db.insert_runtime_config(session_id=sid, config=runtime_config)
        self.db.insert_feature_flag_snapshot(
            session_id=sid,
            snapshot=self.settings.snapshot_flags(),
        )
        self._emit("session_created", sid, None, None, {"mode": profile.name})
        return {
            "session_id": sid,
            "mode": profile.name,
            "runtime_config_hash": runtime_hash,
            "reconnected": False,
        }

    def execute_single(
        self,
        session_id: str,
        provider_id: str,
        prompt: str,
        dataset_version: Optional[str] = None,
        model_override: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        session = self._require_session(session_id)
        request = ProviderRequest(
            prompt=prompt,
            model=model_override or "",
            dataset_version=dataset_version,
            metadata=metadata or {},
        )
        response = self.router.invoke_single(provider_id, request)
        trace = self._persist_execution_result(
            session_id=session_id,
            mode=session["mode"],
            prompt=prompt,
            dataset_version=dataset_version,
            response=response,
        )
        self._emit(
            "execution_single_completed",
            session_id,
            trace.execution_id,
            provider_id,
            {"trace_id": trace.trace_id},
        )
        return self._trace_to_dict(trace)

    def execute_comparative(
        self,
        session_id: str,
        provider_ids: list[str],
        prompt: str,
        dataset_version: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        session = self._require_session(session_id)
        request = ProviderRequest(
            prompt=prompt,
            model="",
            dataset_version=dataset_version,
            metadata=metadata or {},
        )
        comparative = self.router.invoke_comparative(provider_ids, request)
        traces: list[CanonicalInferenceTrace] = []
        for provider_id, response in comparative.responses.items():
            traces.append(
                self._persist_execution_result(
                    session_id=session_id,
                    mode=session["mode"],
                    prompt=prompt,
                    dataset_version=dataset_version,
                    response=response,
                )
            )

        diff_rows = []
        should_diff = self.settings.KURO_PLAYGROUND_EPISTEMIC_DIFF or session["mode"] == "comparative"
        if should_diff:
            diff_rows = compute_epistemic_diff(traces)
            for row in diff_rows:
                self.db.insert_epistemic_diff(
                    session_id=session_id,
                    prompt_sha256=row["prompt_sha256"],
                    left_trace_id=row["left_trace_id"],
                    right_trace_id=row["right_trace_id"],
                    divergence_score=row["divergence_score"],
                    payload=row,
                )
        self._emit(
            "execution_comparative_completed",
            session_id,
            None,
            None,
            {"providers": provider_ids, "trace_count": len(traces)},
        )
        return {
            "prompt_sha256": comparative.prompt_sha256,
            "traces": [self._trace_to_dict(t) for t in traces],
            "epistemic_diffs": diff_rows,
        }

    def reconstruct_ontology(self, session_id: str) -> dict:
        self._require_session(session_id)
        traces = self._load_session_traces(session_id)
        graph = reconstruct_ontology_graph(traces)
        graph_id = self.db.insert_ontology_graph(
            session_id=session_id,
            graph_version="1.0.0",
            graph_jsonld=export_jsonld(graph),
            graph_rdf_star=export_rdf_star(graph),
            alignment_score=None,
        )
        for node in graph.nodes:
            related_edges = [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "relation": edge.relation,
                    "weight": edge.weight,
                }
                for edge in graph.edges
                if edge.source == node.node_id or edge.target == node.node_id
            ]
            self.db.insert_ontology_mapping(
                session_id=session_id,
                trace_id=traces[0].trace_id if traces else "",
                node_id=node.node_id,
                node_label=node.label,
                edges=related_edges,
            )
        self._emit(
            "ontology_reconstructed",
            session_id,
            None,
            None,
            {"graph_id": graph_id, "nodes": len(graph.nodes), "edges": len(graph.edges)},
        )
        return {
            "graph_id": graph_id,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "jsonld": export_jsonld(graph),
            "rdf_star": export_rdf_star(graph),
        }

    def build_and_export_report(self, session_id: str, report_format: str, output_path: Optional[str] = None) -> dict:
        session = self._require_session(session_id)
        traces = self._load_session_traces(session_id)
        raw_rows = self.db.list_raw_evidence(session_id=session_id)
        runtime_rows = self.db.list_runtime_configs(session_id=session_id)
        runtime_config = {}
        if runtime_rows:
            runtime_config = json.loads(runtime_rows[0]["config_json"])
        executions = self.db.list_model_executions(session_id=session_id)
        providers = []
        seen = set()
        for row in executions:
            key = (row["provider_id"], row["model_id"], row["model_version"])
            if key in seen:
                continue
            seen.add(key)
            providers.append(
                {
                    "provider_id": row["provider_id"],
                    "model_id": row["model_id"],
                    "model_version": row["model_version"],
                }
            )
        report = build_report(
            session_id=session_id,
            mode=session["mode"],
            traces=traces,
            runtime_config=runtime_config,
            providers=providers,
            raw_evidence_rows=raw_rows,
            ontology_graph=None,
        )
        rendered = self.report_exporter.export(report=report, fmt=report_format, output_path=output_path)
        fingerprint = sha256(rendered.encode("utf-8")).hexdigest()
        reproducibility_id = self.db.insert_reproducibility_record(
            session_id=session_id,
            execution_id=None,
            prompt_sha256=traces[0].prompt_sha256 if traces else "",
            dataset_version=traces[0].dataset_version if traces else None,
            seed=None,
            execution_fingerprint=fingerprint,
        )
        report_id = self.db.insert_forensic_report(
            session_id=session_id,
            report_format=report_format.lower(),
            report_body=rendered,
            reproducibility_record_id=reproducibility_id,
            artifact_path=output_path,
        )
        self._emit(
            "report_exported",
            session_id,
            None,
            None,
            {"report_id": report_id, "format": report_format.lower()},
        )
        return {
            "report_id": report_id,
            "format": report_format.lower(),
            "report_body": rendered,
            "reproducibility_record_id": reproducibility_id,
            "artifact_path": output_path,
        }

    def list_session_traces(self, session_id: str) -> list[dict]:
        self._require_session(session_id)
        return self.db.list_canonical_traces(session_id=session_id)

    def list_sessions(self, limit: int = 20, mode: Optional[str] = None) -> list[dict]:
        rows = self.db.list_sessions(limit=limit, mode=mode)
        sessions: list[dict] = []
        for row in rows:
            sessions.append(
                {
                    "session_id": row["id"],
                    "mode": row["mode"],
                    "status": row["status"],
                    "created_at_utc": row["created_at_utc"],
                    "ended_at_utc": row["ended_at_utc"],
                    "runtime_config_hash": row["runtime_config_hash"],
                    "notes": row.get("notes", ""),
                }
            )
        return sessions

    def get_latest_session(self) -> dict | None:
        row = self.db.get_latest_session()
        if not row:
            return None
        return {
            "session_id": row["id"],
            "mode": row["mode"],
            "status": row["status"],
            "created_at_utc": row["created_at_utc"],
            "ended_at_utc": row["ended_at_utc"],
            "runtime_config_hash": row["runtime_config_hash"],
            "notes": row.get("notes", ""),
        }

    def get_session_history(self, session_id: str) -> dict:
        session = self._require_session(session_id)
        runtime_rows = self.db.list_runtime_configs(session_id=session_id)
        feature_rows = self.db.list_feature_flag_snapshots(session_id=session_id)
        executions = self.db.list_session_executions(session_id=session_id)
        traces = self.db.list_canonical_traces(session_id=session_id)
        reports = self.db.list_forensic_reports(session_id=session_id)
        diffs = self.db.list_epistemic_diffs(session_id=session_id)
        graphs = self.db.list_ontology_graphs(session_id=session_id)
        reproducibility = self.db.list_reproducibility_records(session_id=session_id)

        return {
            "session": {
                "session_id": session["id"],
                "mode": session["mode"],
                "status": session["status"],
                "created_at_utc": session["created_at_utc"],
                "ended_at_utc": session["ended_at_utc"],
                "runtime_config_hash": session["runtime_config_hash"],
                "notes": session.get("notes", ""),
            },
            "runtime_configs": {
                "latest": self._decode_json(runtime_rows[0]["config_json"], {}) if runtime_rows else {},
                "items": [
                    {
                        "id": row["id"],
                        "created_at_utc": row["created_at_utc"],
                        "config": self._decode_json(row["config_json"], {}),
                    }
                    for row in runtime_rows
                ],
            },
            "feature_flag_snapshots": {
                "latest": self._decode_json(feature_rows[0]["snapshot_json"], {}) if feature_rows else {},
                "items": [
                    {
                        "id": row["id"],
                        "created_at_utc": row["created_at_utc"],
                        "snapshot": self._decode_json(row["snapshot_json"], {}),
                    }
                    for row in feature_rows
                ],
            },
            "executions": [
                {
                    "execution_id": row["id"],
                    "created_at_utc": row["created_at_utc"],
                    "provider_id": row["provider_id"],
                    "model_id": row["model_id"],
                    "model_version": row["model_version"],
                    "request_id": row["request_id"],
                    "prompt_sha256": row["prompt_sha256"],
                    "dataset_version": row["dataset_version"],
                    "latency_ms": row["latency_ms"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "total_tokens": row["total_tokens"],
                    "finish_reason": row["finish_reason"],
                }
                for row in executions
            ],
            "traces_summary": {
                "count": len(traces),
                "latest_collected_at_utc": traces[-1]["collected_at_utc"] if traces else None,
            },
            "reports": [
                {
                    "report_id": row["id"],
                    "report_format": row["report_format"],
                    "created_at_utc": row["created_at_utc"],
                    "artifact_path": row["artifact_path"],
                }
                for row in reports
            ],
            "epistemic_diffs": {
                "count": len(diffs),
                "items": [
                    {
                        "id": row["id"],
                        "prompt_sha256": row["prompt_sha256"],
                        "left_trace_id": row["left_trace_id"],
                        "right_trace_id": row["right_trace_id"],
                        "divergence_score": row["divergence_score"],
                        "created_at_utc": row["created_at_utc"],
                    }
                    for row in diffs[:20]
                ],
            },
            "ontology_graphs": {
                "count": len(graphs),
                "items": [
                    {
                        "id": row["id"],
                        "graph_version": row["graph_version"],
                        "alignment_score": row["alignment_score"],
                        "created_at_utc": row["created_at_utc"],
                    }
                    for row in graphs[:20]
                ],
            },
            "reproducibility_records": [
                {
                    "id": row["id"],
                    "execution_id": row["execution_id"],
                    "prompt_sha256": row["prompt_sha256"],
                    "dataset_version": row["dataset_version"],
                    "seed": row["seed"],
                    "execution_fingerprint": row["execution_fingerprint"],
                    "created_at_utc": row["created_at_utc"],
                }
                for row in reproducibility
            ],
        }

    def build_session_json_artifact(
        self,
        session_id: str,
        artifact_type: str,
        execution_id: Optional[str] = None,
    ) -> tuple[str, str]:
        if artifact_type == "session":
            payload = self.get_session_history(session_id=session_id)
            return (f"playground-session-{session_id}.json", json.dumps(payload, ensure_ascii=False, indent=2))

        if artifact_type not in {"execution_raw", "execution_trace"}:
            raise PlaygroundError("artifact type must be one of: session, execution_raw, execution_trace")
        if not execution_id:
            raise PlaygroundError("execution_id is required for execution_raw and execution_trace artifacts")

        self._require_session(session_id)
        execution = self.db.get_model_execution(execution_id=execution_id)
        if not execution or execution["session_id"] != session_id:
            raise PlaygroundError(f"Unknown execution_id '{execution_id}' for session '{session_id}'")

        if artifact_type == "execution_raw":
            raw = self.db.get_raw_evidence_by_execution(execution_id=execution_id)
            if not raw:
                raise PlaygroundError(f"No raw evidence found for execution_id '{execution_id}'")
            payload = {
                "session_id": session_id,
                "artifact_type": artifact_type,
                "execution": execution,
                "raw_evidence": {
                    **raw,
                    "raw_json": self._decode_json(raw.get("raw_json"), {}),
                },
            }
            return (f"playground-exec-raw-{execution_id}.json", json.dumps(payload, ensure_ascii=False, indent=2))

        trace = self.db.get_canonical_trace_by_execution(execution_id=execution_id)
        if not trace:
            raise PlaygroundError(f"No canonical trace found for execution_id '{execution_id}'")
        payload = {
            "session_id": session_id,
            "artifact_type": artifact_type,
            "execution": execution,
            "canonical_trace": {
                **trace,
                "grounding_chunks_json": self._decode_json(trace.get("grounding_chunks_json"), []),
                "citation_objects_json": self._decode_json(trace.get("citation_objects_json"), []),
                "safety_ratings_json": self._decode_json(trace.get("safety_ratings_json"), None),
                "forensic_flags_json": self._decode_json(trace.get("forensic_flags_json"), []),
                "normalization_warnings_json": self._decode_json(trace.get("normalization_warnings_json"), []),
                "extra_fields_json": self._decode_json(trace.get("extra_fields_json"), {}),
            },
        }
        return (f"playground-exec-trace-{execution_id}.json", json.dumps(payload, ensure_ascii=False, indent=2))

    def _require_session(self, session_id: str) -> dict:
        session = self.db.get_session(session_id)
        if not session:
            raise PlaygroundError(f"Unknown session_id '{session_id}'")
        return session

    def _emit(
        self,
        event_type: str,
        session_id: str,
        execution_id: Optional[str],
        provider_id: Optional[str],
        payload: dict,
    ) -> None:
        if not self.telemetry:
            return
        self.telemetry.emit(
            event_type=event_type,
            session_id=session_id,
            execution_id=execution_id,
            provider_id=provider_id,
            payload=payload,
        )

    def _persist_execution_result(
        self,
        session_id: str,
        mode: str,
        prompt: str,
        dataset_version: Optional[str],
        response: ProviderResponse,
    ) -> CanonicalInferenceTrace:
        prompt_sha = sha256(prompt.encode("utf-8")).hexdigest()
        execution_id = self.db.insert_model_execution(
            session_id=session_id,
            provider_id=response.provider_id,
            model_id=response.model_id,
            model_version=response.model_version,
            request_id=response.request_id,
            prompt_sha256=prompt_sha,
            dataset_version=dataset_version,
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            finish_reason=response.finish_reason,
        )
        artifact = EvidenceArtifact(
            provider_id=response.provider_id,
            model_version=response.model_version,
            response_schema_version="provider_raw/1.0",
            request_id=response.request_id,
            prompt_sha256=prompt_sha,
            dataset_version=dataset_version,
            collected_at_utc=response.collected_at_utc,
            raw_json=response.raw_json,
        )
        raw_id = self.evidence_store.persist_raw_evidence(
            session_id=session_id,
            execution_id=execution_id,
            artifact=artifact,
        )
        normalized_input = {
            "provider_id": response.provider_id,
            "model_id": response.model_id,
            "model_version": response.model_version,
            "prompt": prompt,
            "response_text": response.response_text,
            "finish_reason": response.finish_reason,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
            "latency_ms": response.latency_ms,
            "collected_at_utc": response.collected_at_utc,
            "dataset_version": dataset_version,
        }
        if isinstance(response.raw_json, dict):
            for key in (
                "reasoning",
                "reasoning_content",
                "chain_of_thought",
                "cot",
                "thought_process",
                "internal_reasoning",
            ):
                if key in response.raw_json:
                    normalized_input[key] = response.raw_json[key]
            if isinstance(response.raw_json.get("grounding_chunks"), list):
                normalized_input["grounding_chunks"] = response.raw_json.get("grounding_chunks")
            if isinstance(response.raw_json.get("citations"), list):
                normalized_input["citation_objects"] = response.raw_json.get("citations")
            if isinstance(response.raw_json.get("citation_objects"), list):
                normalized_input["citation_objects"] = response.raw_json.get("citation_objects")
            if isinstance(response.raw_json.get("safety_ratings"), dict):
                normalized_input["safety_ratings"] = response.raw_json.get("safety_ratings")
        trace = self.normalization.normalize(
            session_id=session_id,
            execution_id=execution_id,
            provider_raw_id=raw_id,
            raw_record=normalized_input,
        )
        self.db.insert_canonical_trace(trace)

        if self.settings.KURO_PLAYGROUND_HALLUCINATION_ANALYZER:
            hallucination = analyze_trace(trace)
            if hallucination["is_hallucination_risk"]:
                self.db.insert_hallucination_record(
                    session_id=session_id,
                    execution_id=execution_id,
                    trace_id=trace.trace_id,
                    risk_score=hallucination["risk_score"],
                    flags=hallucination["flags"],
                    evidence={"prompt_sha256": trace.prompt_sha256, "provider_raw_id": raw_id},
                )
                if mode == "forensic":
                    raise ProviderExecutionError(
                        f"FORENSIC_HOLD: hallucination risk detected for trace {trace.trace_id}"
                    )
        return trace

    @staticmethod
    def _trace_to_dict(trace: CanonicalInferenceTrace) -> dict:
        row = asdict(trace)
        row["collected_at_utc"] = trace.collected_at_utc.isoformat()
        return row

    def _load_session_traces(self, session_id: str) -> list[CanonicalInferenceTrace]:
        rows = self.db.list_canonical_traces(session_id=session_id)
        traces: list[CanonicalInferenceTrace] = []
        for row in rows:
            traces.append(
                CanonicalInferenceTrace(
                    trace_id=row["id"],
                    session_id=row["session_id"],
                    execution_id=row["execution_id"],
                    provider_id=row["provider_id"],
                    model_id=row["model_id"],
                    model_version=row["model_version"],
                    schema_version=row["schema_version"],
                    prompt_sha256=row["prompt_sha256"],
                    dataset_version=row["dataset_version"],
                    collected_at_utc=datetime.fromisoformat(row["collected_at_utc"]),
                    response_text=row["response_text"],
                    finish_reason=row["finish_reason"],
                    input_tokens=row["input_tokens"],
                    output_tokens=row["output_tokens"],
                    total_tokens=row["total_tokens"],
                    latency_ms=row["latency_ms"],
                    grounding_chunks=self._decode_json(row["grounding_chunks_json"], []),
                    citation_objects=self._decode_json(row["citation_objects_json"], []),
                    safety_ratings=self._decode_json(row["safety_ratings_json"], None),
                    provider_raw_id=row["provider_raw_id"],
                    forensic_flags=self._decode_json(row["forensic_flags_json"], []),
                    normalization_warnings=self._decode_json(row["normalization_warnings_json"], []),
                    extra_fields=self._decode_json(row["extra_fields_json"], {}),
                )
            )
        return traces

    @staticmethod
    def _decode_json(raw: Any, default: Any) -> Any:
        if raw is None:
            return default
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return default
