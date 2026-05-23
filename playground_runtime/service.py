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
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional

from playground_runtime.config import PlaygroundSettings, get_settings
from playground_runtime.db.playground_db import PlaygroundDB
from playground_runtime.errors import PlaygroundError, ProviderExecutionError
from playground_runtime.evaluation.report_builder import build_report
from playground_runtime.export.forensic_bundle_exporter import ForensicBundleExporter
from playground_runtime.export.report_exporter import ReportExporter
from playground_runtime.divergence.semantic_diff import compute_semantic_divergence
from playground_runtime.forensic.epistemic_diff import compute_epistemic_diff
from playground_runtime.forensic.evidence_store import EvidenceStore
from playground_runtime.forensic.hallucination_analyzer import analyze_trace
from playground_runtime.governance.boundary_validator import validate_playground_imports
from playground_runtime.governance.isolation_gate import IsolationGate
from playground_runtime.integrity.artifact_hashing import canonical_json_dumps, sha256_json
from playground_runtime.integrity.chain_of_custody import build_custody_event
from playground_runtime.integrity.evidence_snapshot import build_snapshot_bundle
from playground_runtime.integrity.forensic_verification import verify_hash
from playground_runtime.integrity.provenance_integrity import (
    capability_snapshot_hash,
    capability_snapshot_payload,
)
from playground_runtime.integrity.transformation_manifest import build_transformation_manifest
from playground_runtime.modes import resolve_mode_profile
from playground_runtime.ontology.graph_exporter import export_jsonld, export_rdf_star
from playground_runtime.ontology.reconstructor import reconstruct_ontology_graph
from playground_runtime.providers.capabilities.catalog import extend_capability_payload
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
        self.bundle_exporter = ForensicBundleExporter()

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
        actor: Optional[str] = None,
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

        env_flags = self.settings.snapshot_flags()
        runtime_config = {
            "mode": profile.name,
            "profile": asdict(profile),
            "flags": env_flags,
            "selected_mode": profile.name,
            "effective_workflow_mode": "quick",
            "env_feature_flags": env_flags,
            "ui_selected_providers": [],
            "provider_count": 0,
            "effective_features": {
                "comparative_execution_enabled": False,
                "forensic_integrity_enabled": False,
                "ontology_graph_enabled": profile.name == "ontology",
                "report_export_enabled": False,
            },
            "comparative_execution_enabled": False,
            "forensic_integrity_enabled": False,
            "ontology_graph_enabled": profile.name == "ontology",
            "report_export_enabled": False,
            "feature_sources": ["env", "runtime_profile"],
            "feature_source": "mixed",
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
        for provider_id in self.registry.list_active():
            spec = self.registry.get_capability_spec(provider_id)
            payload = extend_capability_payload(provider_id, capability_snapshot_payload(spec))
            cap_hash = capability_snapshot_hash(spec)
            self.db.insert_provider_capability(
                session_id=sid,
                provider_id=provider_id,
                capability_json=payload,
                capability_hash=cap_hash,
            )
            self._record_custody_event(
                build_custody_event(
                    artifact_id=provider_id,
                    action_type="PROVIDER_CAPABILITY_SNAPSHOT",
                    actor=actor,
                    new_hash=cap_hash,
                    notes=f"session_id={sid}",
                )
            )
        self._emit("session_created", sid, None, None, {"mode": profile.name})
        self._record_custody_event(
            build_custody_event(
                artifact_id=sid,
                action_type="SESSION_CREATED",
                actor=actor,
                notes=f"mode={profile.name}",
            )
        )
        self.build_session_timeline_integrity(session_id=sid, actor=actor)
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
        actor: Optional[str] = None,
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
            actor=actor,
        )
        self._emit(
            "execution_single_completed",
            session_id,
            trace.execution_id,
            provider_id,
            {"trace_id": trace.trace_id},
        )
        self._update_runtime_config_state(
            session_id=session_id,
            source="ui",
            selected_mode=session.get("mode", "research"),
            ui_selected_providers=[provider_id],
            provider_count=1,
            effective_features={
                "comparative_execution_enabled": False,
                "forensic_integrity_enabled": True,
            },
        )
        self.build_session_timeline_integrity(session_id=session_id, actor=actor)
        return self._trace_to_dict(trace)

    def execute_comparative(
        self,
        session_id: str,
        provider_ids: list[str],
        prompt: str,
        dataset_version: Optional[str] = None,
        metadata: Optional[dict] = None,
        actor: Optional[str] = None,
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
                    actor=actor,
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
        divergence_rows = compute_semantic_divergence(traces)
        for row in divergence_rows:
            self.db.insert_semantic_divergence(session_id=session_id, payload=row)
        self._update_runtime_config_state(
            session_id=session_id,
            source="ui",
            selected_mode=session.get("mode", "research"),
            ui_selected_providers=provider_ids,
            provider_count=len(provider_ids),
            effective_features={
                "comparative_execution_enabled": len(provider_ids) > 1,
                "forensic_integrity_enabled": True,
            },
            effective_workflow_mode="comparative" if len(provider_ids) > 1 else "quick",
        )
        self._emit(
            "execution_comparative_completed",
            session_id,
            None,
            None,
            {"providers": provider_ids, "trace_count": len(traces)},
        )
        self.build_session_timeline_integrity(session_id=session_id, actor=actor)
        return {
            "prompt_sha256": comparative.prompt_sha256,
            "traces": [self._trace_to_dict(t) for t in traces],
            "epistemic_diffs": diff_rows,
            "semantic_divergence": divergence_rows,
        }

    def reconstruct_ontology(self, session_id: str, actor: Optional[str] = None) -> dict:
        session = self._require_session(session_id)
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
            self.db.insert_ontology_entity(
                graph_id=graph_id,
                entity_id=node.node_id,
                label=node.label,
                entity_type="concept",
                provenance={"session_id": session_id},
            )
        for edge in graph.edges:
            self.db.insert_ontology_relationship(
                graph_id=graph_id,
                source_entity_id=edge.source,
                target_entity_id=edge.target,
                relation=edge.relation,
                weight=edge.weight,
                provenance={"session_id": session_id},
            )
        self._update_runtime_config_state(
            session_id=session_id,
            source="runtime_profile",
            selected_mode=session.get("mode", "research"),
            effective_features={"ontology_graph_enabled": True},
        )
        self._emit(
            "ontology_reconstructed",
            session_id,
            None,
            None,
            {"graph_id": graph_id, "nodes": len(graph.nodes), "edges": len(graph.edges)},
        )
        self._record_custody_event(
            build_custody_event(
                artifact_id=graph_id,
                action_type="ONTOLOGY_RECONSTRUCTED",
                actor=actor,
                notes=f"session_id={session_id}",
            )
        )
        return {
            "graph_id": graph_id,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "jsonld": export_jsonld(graph),
            "rdf_star": export_rdf_star(graph),
        }

    def build_and_export_report(
        self,
        session_id: str,
        report_format: str,
        output_path: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> dict:
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
        report_hash = sha256(rendered.encode("utf-8")).hexdigest()
        self.db.insert_artifact_integrity(
            artifact_id=report_id,
            artifact_type="forensic_report",
            sha256_value=report_hash,
            acquisition_session=session_id,
            verification_status="verified",
        )
        self._record_custody_event(
            build_custody_event(
                artifact_id=report_id,
                action_type="REPORT_EXPORTED",
                actor=actor,
                new_hash=report_hash,
                notes=f"format={report_format.lower()}",
            )
        )
        self._emit(
            "report_exported",
            session_id,
            None,
            None,
            {"report_id": report_id, "format": report_format.lower()},
        )
        self._update_runtime_config_state(
            session_id=session_id,
            source="runtime_profile",
            selected_mode=session.get("mode", "research"),
            effective_features={"report_export_enabled": True},
        )
        self.build_session_timeline_integrity(session_id=session_id, actor=actor)
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
                    "session_integrity_hash": row.get("session_integrity_hash"),
                    "session_integrity_status": str(row.get("session_integrity_status") or "unverified").upper(),
                    "session_integrity_verified_at": row.get("session_integrity_verified_at"),
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
            "session_integrity_hash": row.get("session_integrity_hash"),
            "session_integrity_status": str(row.get("session_integrity_status") or "unverified").upper(),
            "session_integrity_verified_at": row.get("session_integrity_verified_at"),
        }

    def get_session_history(self, session_id: str) -> dict:
        self._require_session(session_id)
        runtime_rows = self.db.list_runtime_configs(session_id=session_id)
        feature_rows = self.db.list_feature_flag_snapshots(session_id=session_id)
        executions = self.db.list_session_executions(session_id=session_id)
        traces = self.db.list_canonical_traces(session_id=session_id)
        reports = self.db.list_forensic_reports(session_id=session_id)
        diffs = self.db.list_epistemic_diffs(session_id=session_id)
        semantic_divergence = self.db.list_semantic_divergence(session_id=session_id)
        graphs = self.db.list_ontology_graphs(session_id=session_id)
        reproducibility = self.db.list_reproducibility_records(session_id=session_id)
        integrity_rows = self.db.list_artifact_integrity(session_id=session_id)
        manifests = self.db.list_transformation_manifests(session_id=session_id)
        snapshots = self.db.list_snapshots(session_id=session_id)
        capabilities = self.db.list_provider_capabilities(session_id=session_id)
        artifact_scope = [session_id]
        artifact_scope.extend([row["id"] for row in executions if row.get("id")])
        artifact_scope.extend([row["id"] for row in traces if row.get("id")])
        artifact_scope.extend([row["id"] for row in reports if row.get("id")])
        artifact_scope.extend([row["snapshot_id"] for row in snapshots if row.get("snapshot_id")])
        custody_rows = self.db.list_chain_of_custody_for_artifacts(artifact_scope)
        integrity_overview = self.build_integrity_overview(session_id=session_id, workflow_mode="quick")
        session_timeline = self.build_session_timeline_integrity(session_id=session_id)
        session = self.db.get_session(session_id) or {}
        execution_integrity_rows = [
            self._compact_execution_trust(session_id=session_id, execution_id=row["id"])
            for row in executions[:50]
        ]
        snapshot_trust_rows = [
            self.build_snapshot_trust_summary(session_id=session_id, snapshot_id=row["snapshot_id"])
            for row in snapshots[:50]
            if row.get("snapshot_id")
        ]
        runtime_latest_raw = self._decode_json(runtime_rows[0]["config_json"], {}) if runtime_rows else {}
        runtime_latest = self._ensure_runtime_config_consistency(
            runtime_config=runtime_latest_raw,
            session_mode=session.get("mode", "research"),
            executions=executions,
            reports=reports,
            ontology_graphs=graphs,
        )

        return {
            "session": {
                "session_id": session["id"],
                "mode": session["mode"],
                "status": session["status"],
                "created_at_utc": session["created_at_utc"],
                "ended_at_utc": session["ended_at_utc"],
                "runtime_config_hash": session["runtime_config_hash"],
                "notes": session.get("notes", ""),
                "session_integrity_hash": session.get("session_integrity_hash"),
                "session_integrity_status": str(session.get("session_integrity_status") or "unverified").upper(),
                "session_integrity_verified_at": session.get("session_integrity_verified_at"),
            },
            "runtime_configs": {
                "latest": runtime_latest,
                "items": [
                    {
                        "id": row["id"],
                        "created_at_utc": row["created_at_utc"],
                        "config": self._ensure_runtime_config_consistency(
                            runtime_config=self._decode_json(row["config_json"], {}),
                            session_mode=session.get("mode", "research"),
                            executions=executions,
                            reports=reports,
                            ontology_graphs=graphs,
                        ),
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
            "semantic_divergence": {
                "count": len(semantic_divergence),
                "items": [self._decode_semantic_divergence_row(row) for row in semantic_divergence[:20]],
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
            "artifact_integrity": {
                "count": len(integrity_rows),
                "items": integrity_rows[:50],
            },
            "transformation_manifests": {
                "count": len(manifests),
                "items": [self._decode_manifest_row(row) for row in manifests[:20]],
            },
            "evidence_snapshots": {
                "count": len(snapshots),
                "items": snapshots[:20],
            },
            "provider_capabilities": {
                "count": len(capabilities),
                "items": [self._decode_capability_row(row) for row in capabilities[:20]],
            },
            "chain_of_custody": {
                "count": len(custody_rows),
                "items": custody_rows[:50],
            },
            "integrity_overview": integrity_overview,
            "session_timeline_integrity": session_timeline,
            "execution_integrity_rows": execution_integrity_rows,
            "snapshot_trust_rows": snapshot_trust_rows,
        }

    def build_advisor_context(self, *, session_id: str, workflow_mode: str = "quick") -> dict:
        session = self._require_session(session_id)
        mode = self._normalize_workflow_mode(workflow_mode)
        history = self.get_session_history(session_id=session_id)
        trace_rows = [self._decode_canonical_trace_row(row) for row in self.list_session_traces(session_id=session_id)]
        integrity_overview = self.build_integrity_overview(session_id=session_id, workflow_mode=mode)

        try:
            lineage = self.build_transformation_lineage(session_id=session_id)
            lineage_summary = {
                "available": True,
                "node_count": len(lineage.get("nodes") or []),
                "edge_count": len(lineage.get("edges") or []),
            }
        except Exception:
            lineage_summary = {
                "available": False,
                "node_count": 0,
                "edge_count": 0,
            }

        history_session = history.get("session") or {}
        integrity_status = str(
            session.get("session_integrity_status")
            or history_session.get("session_integrity_status")
            or "unknown"
        ).upper()
        if integrity_status not in {"VERIFIED", "UNVERIFIED", "FAILED"}:
            integrity_status = "UNKNOWN"

        execution_rows = {
            row.get("execution_id"): row
            for row in history.get("executions", [])
            if row.get("execution_id")
        }
        providers = sorted({str(row.get("provider_id")) for row in trace_rows if row.get("provider_id")})
        if not providers:
            providers = sorted(
                {
                    str(row.get("provider_id"))
                    for row in history.get("executions", [])
                    if row.get("provider_id")
                }
            )

        prompt_sha256 = None
        dataset_version = None
        for row in trace_rows or history.get("executions", []):
            prompt_sha256 = row.get("prompt_sha256")
            dataset_version = row.get("dataset_version")
            if prompt_sha256:
                break

        def _first_not_none(value: Any, fallback: Any) -> Any:
            return value if value is not None else fallback

        executions = []
        for trace in trace_rows:
            extra = trace.get("extra_fields_json")
            if not isinstance(extra, dict):
                extra = {}
            execution = execution_rows.get(trace.get("execution_id"), {})
            grounding_chunks = trace.get("grounding_chunks_json") or []
            citation_objects = trace.get("citation_objects_json") or []
            executions.append(
                {
                    "execution_id": trace.get("execution_id"),
                    "trace_id": trace.get("id") or trace.get("trace_id"),
                    "provider_id": trace.get("provider_id"),
                    "model_id": trace.get("model_id"),
                    "schema_version": trace.get("schema_version"),
                    "environment": self._advisor_provider_environment(trace.get("provider_id")),
                    "finish_reason": _first_not_none(trace.get("finish_reason"), execution.get("finish_reason")),
                    "token_usage": {
                        "input_tokens": _first_not_none(trace.get("input_tokens"), execution.get("input_tokens")),
                        "output_tokens": _first_not_none(trace.get("output_tokens"), execution.get("output_tokens")),
                        "total_tokens": _first_not_none(trace.get("total_tokens"), execution.get("total_tokens")),
                    },
                    "latency_ms": _first_not_none(trace.get("latency_ms"), execution.get("latency_ms")),
                    "forensic_flags": trace.get("forensic_flags_json") or [],
                    "normalization_warnings": trace.get("normalization_warnings_json") or [],
                    "provider_specific_artifact": {
                        "type": extra.get("provider_specific_artifact_type"),
                        "origin": extra.get("provider_specific_artifact_origin")
                        or extra.get("visible_reasoning_trace_origin")
                        or extra.get("reasoning_signature_origin"),
                        "human_readable": extra.get("provider_specific_artifact_human_readable"),
                    },
                    "visible_reasoning_artifact_present": self._advisor_has_value(extra.get("visible_reasoning_trace")),
                    "opaque_reasoning_signature_present": self._advisor_has_value(extra.get("provider_thought_signature"))
                    or self._advisor_has_value(extra.get("opaque_reasoning_signature")),
                    "system_fingerprint_present": self._advisor_has_value(extra.get("system_fingerprint")),
                    "grounding_present": bool(grounding_chunks),
                    "citations_present": bool(citation_objects),
                    "response_preview": self._advisor_response_preview(trace.get("response_text")),
                }
            )

        semantic_divergence = []
        divergence_items = (history.get("semantic_divergence") or {}).get("items") or []
        for row in divergence_items:
            metadata_delta = row.get("metadata_surface_delta")
            if not isinstance(metadata_delta, dict):
                metadata_delta = {}
            semantic_divergence.append(
                {
                    "left_trace_id": row.get("left_trace_id"),
                    "right_trace_id": row.get("right_trace_id"),
                    "classification_label_left": row.get("classification_label_left"),
                    "classification_label_right": row.get("classification_label_right"),
                    "classification_agreement": row.get("classification_agreement"),
                    "contradiction_detected": row.get("contradiction_detected"),
                    "semantic_overlap": row.get("semantic_overlap"),
                    "claim_overlap": row.get("claim_overlap"),
                    "rationale_overlap": row.get("rationale_overlap"),
                    "output_length_delta": row.get("output_length_delta"),
                    "token_delta": row.get("token_delta"),
                    "latency_delta_ms": row.get("latency_delta_ms"),
                    "metadata_surface_delta": {
                        "left_only": metadata_delta.get("left_only") or [],
                        "right_only": metadata_delta.get("right_only") or [],
                        "delta_count": metadata_delta.get("delta_count", 0),
                    },
                    "visible_reasoning_delta": row.get("visible_reasoning_delta"),
                    "provider_specific_artifact_delta": row.get("provider_specific_artifact_delta"),
                }
            )

        return {
            "context_type": "playground_advisor_context",
            "session": {
                "session_id": history_session.get("session_id") or session.get("id"),
                "mode": history_session.get("mode") or session.get("mode"),
                "status": history_session.get("status") or session.get("status"),
                "created_at_utc": history_session.get("created_at_utc") or session.get("created_at_utc"),
                "integrity_status": integrity_status,
            },
            "prompt": {
                "prompt_sha256": prompt_sha256,
                "dataset_version": dataset_version,
            },
            "providers": providers,
            "executions": executions,
            "semantic_divergence": semantic_divergence,
            "integrity_overview": {
                "metrics": integrity_overview.get("metrics") or {},
                "alerts": integrity_overview.get("alerts") or [],
            },
            "transformation_lineage": lineage_summary,
            "forensic_interpretation_hints": [
                "Separate semantic agreement from artifact-surface divergence.",
                "Do not treat visible reasoning artifacts as true hidden chain-of-thought.",
                "Do not treat opaque provider thought signatures as human-readable reasoning.",
                "Raw evidence is preserved in Playground but omitted from Advisor Context by default.",
                "Canonical traces are derived forensic representations and should remain traceable to raw evidence.",
            ],
            "limitations": [
                "Advisor Context is derived only from observable Playground artifacts.",
                "It does not provide model intent, model weights, hidden reasoning, or private provider internals.",
                "Raw evidence can be inspected through existing Playground artifact endpoints, not dumped into Advisor prompt context by default.",
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

    def create_snapshot(
        self,
        *,
        session_id: str,
        execution_id: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> dict:
        self._require_session(session_id)
        if execution_id:
            execution = self.db.get_model_execution(execution_id=execution_id)
            if not execution or execution["session_id"] != session_id:
                raise PlaygroundError(f"Unknown execution_id '{execution_id}' for session '{session_id}'")
            raw_rows = [self.db.get_raw_evidence_by_execution(execution_id)] if execution_id else []
            trace_rows = [self.db.get_canonical_trace_by_execution(execution_id)] if execution_id else []
            raw_rows = [r for r in raw_rows if r]
            trace_rows = [r for r in trace_rows if r]
        else:
            raw_rows = self.db.list_raw_evidence(session_id=session_id)
            trace_rows = self.db.list_canonical_traces(session_id=session_id)

        manifests = self.db.list_transformation_manifests(session_id=session_id, execution_id=execution_id)
        integrity_rows = self.db.list_artifact_integrity(session_id=session_id)
        runtime_rows = self.db.list_runtime_configs(session_id=session_id)
        runtime_config = self._decode_json(runtime_rows[0]["config_json"], {}) if runtime_rows else {}
        capability_rows = self.db.list_provider_capabilities(session_id=session_id)

        bundle, snapshot_hash = build_snapshot_bundle(
            session_id=session_id,
            execution_id=execution_id,
            raw_evidence=[self._decode_raw_evidence_row(row) for row in raw_rows],
            canonical_traces=[self._decode_canonical_trace_row(row) for row in trace_rows],
            transformation_manifests=[self._decode_manifest_row(row) for row in manifests],
            integrity_rows=integrity_rows,
            provider_capabilities=[self._decode_capability_row(row) for row in capability_rows],
            runtime_config=runtime_config,
        )
        snapshot_id = self.db.insert_evidence_snapshot(
            session_id=session_id,
            execution_id=execution_id,
            snapshot_hash=snapshot_hash,
            snapshot_bundle_json=canonical_json_dumps(bundle),
            verification_status="unverified",
        )
        self.db.insert_artifact_integrity(
            artifact_id=snapshot_id,
            artifact_type="evidence_snapshot",
            sha256_value=snapshot_hash,
            acquisition_session=session_id,
            verification_status="unverified",
        )
        self._record_custody_event(
            build_custody_event(
                artifact_id=snapshot_id,
                action_type="SNAPSHOT_CREATED",
                actor=actor,
                new_hash=snapshot_hash,
                notes=f"session_id={session_id}",
            )
        )
        self.build_session_timeline_integrity(session_id=session_id, actor=actor)
        return {
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
            "verification_status": "unverified",
            "bundle": bundle,
        }

    def verify_snapshot(self, *, session_id: str, snapshot_id: str, actor: Optional[str] = None) -> dict:
        self._require_session(session_id)
        row = self.db.get_snapshot(snapshot_id)
        if not row or row["session_id"] != session_id:
            raise PlaygroundError(f"Unknown snapshot_id '{snapshot_id}' for session '{session_id}'")
        bundle = self._decode_json(row.get("snapshot_bundle_json"), {})
        recalculated = sha256_json(bundle)
        checks = [verify_hash(expected_sha256=row["snapshot_hash"], payload=bundle)]
        raw_rows = bundle.get("raw_evidence", []) if isinstance(bundle, dict) else []
        for raw in raw_rows:
            rid = raw.get("id")
            if not rid:
                continue
            db_row = self.db.get_raw_evidence_by_id(rid)
            if not db_row:
                checks.append({"artifact_id": rid, "verified": False, "reason": "missing_raw"})
                continue
            checks.append(
                {
                    "artifact_id": rid,
                    **verify_hash(expected_sha256=raw.get("raw_sha256", ""), text=db_row.get("raw_json", "")),
                }
            )
        verified = all(bool(c.get("verified")) for c in checks) and recalculated == row["snapshot_hash"]
        status = "verified" if verified else "failed"
        self.db.update_evidence_snapshot_verification(snapshot_id=snapshot_id, verification_status=status)
        self._record_custody_event(
            build_custody_event(
                artifact_id=snapshot_id,
                action_type="SNAPSHOT_VERIFIED",
                actor=actor,
                previous_hash=row["snapshot_hash"],
                new_hash=recalculated,
                notes=f"status={status}",
            )
        )
        return {
            "snapshot_id": snapshot_id,
            "expected_hash": row["snapshot_hash"],
            "recalculated_hash": recalculated,
            "verification_status": status,
            "checks": checks,
            "trust_summary": self.build_snapshot_trust_summary(session_id=session_id, snapshot_id=snapshot_id),
        }

    def build_forensic_view(self, *, session_id: str, view: str, workflow_mode: str = "quick") -> dict:
        session = self._require_session(session_id)
        mode = self._normalize_workflow_mode(workflow_mode)
        self._update_runtime_config_state(
            session_id=session_id,
            source="ui",
            selected_mode=session.get("mode", "research"),
            effective_workflow_mode=mode,
        )
        view_name = (view or "summary").strip().lower()
        if view_name == "raw":
            rows = self.db.list_raw_evidence(session_id=session_id)
            payload = {"view": "raw", "session_id": session_id, "items": [self._decode_raw_evidence_row(r) for r in rows]}
            return self._shape_view_payload(payload, mode)
        if view_name == "canonical":
            rows = self.db.list_canonical_traces(session_id=session_id)
            payload = {"view": "canonical", "session_id": session_id, "items": [self._decode_canonical_trace_row(r) for r in rows]}
            return self._shape_view_payload(payload, mode)
        if view_name == "ontology":
            rows = self.db.list_ontology_graphs(session_id=session_id)
            minimal_graphs = self._build_minimal_ontology_graphs(session_id=session_id)
            payload = {
                "view": "ontology",
                "session_id": session_id,
                "graphs": minimal_graphs,
                "stored_graphs": rows,
            }
            if minimal_graphs:
                self._update_runtime_config_state(
                    session_id=session_id,
                    source="runtime_profile",
                    selected_mode=session.get("mode", "research"),
                    effective_features={"ontology_graph_enabled": True},
                )
            return self._shape_view_payload(payload, mode)
        if view_name == "divergence":
            rows = self.db.list_semantic_divergence(session_id=session_id)
            payload = {"view": "divergence", "session_id": session_id, "items": [self._decode_semantic_divergence_row(r) for r in rows]}
            return self._shape_view_payload(payload, mode)
        if view_name != "summary":
            raise PlaygroundError("view must be one of: raw, canonical, summary, ontology, divergence")
        history = self.get_session_history(session_id=session_id)
        divergence_rows = self.db.list_semantic_divergence(session_id=session_id)
        payload = {
            "view": "summary",
            "session_id": session_id,
            "workflow_mode": mode,
            "summary": {
                "execution_count": len(history.get("executions", [])),
                "trace_count": history.get("traces_summary", {}).get("count", 0),
                "report_count": len(history.get("reports", [])),
                "divergence_pairs": len(divergence_rows),
            },
            "narrative": self._build_forensic_narrative(history, divergence_rows),
            "integrity_overview": self.build_integrity_overview(session_id=session_id, workflow_mode=mode),
        }
        return self._shape_view_payload(payload, mode)

    def build_integrity_overview(self, *, session_id: str, workflow_mode: str = "quick") -> dict:
        self._require_session(session_id)
        mode = self._normalize_workflow_mode(workflow_mode)
        artifacts = self.db.list_artifact_integrity(session_id=session_id)
        traces = self.db.list_canonical_traces(session_id=session_id)
        snapshots = self.db.list_snapshots(session_id=session_id)
        manifests = self.db.list_transformation_manifests(session_id=session_id)

        verified_count = sum(1 for row in artifacts if str(row.get("verification_status", "")).lower() == "verified")
        failed_count = sum(1 for row in artifacts if str(row.get("verification_status", "")).lower() in {"failed", "corrupted"})
        drift_count = 0
        unresolved_mapping = 0
        for trace in traces:
            warnings = self._decode_json(trace.get("normalization_warnings_json"), [])
            if any(str(w).startswith("SCHEMA_DRIFT") for w in warnings):
                drift_count += 1
        for row in manifests:
            sem_flags = self._decode_json(row.get("semantic_loss_flags_json"), [])
            if "UNRESOLVED_PROVIDER_ALIAS" in sem_flags:
                unresolved_mapping += 1

        trace_ids = {row.get("id") for row in traces if row.get("id")}
        execution_ids = {row.get("id") for row in self.db.list_model_executions(session_id=session_id)}
        linked_execution_ids = {row.get("execution_id") for row in traces if row.get("execution_id")}
        orphaned_traces = max(0, len(trace_ids) - len(linked_execution_ids & execution_ids))

        snapshot_mismatches = sum(1 for row in snapshots if str(row.get("verification_status", "")).lower() in {"failed", "corrupted"})
        corrupted_exports = sum(
            1
            for row in artifacts
            if row.get("artifact_type") in {"forensic_bundle_zip", "forensic_report"}
            and str(row.get("verification_status", "")).lower() in {"failed", "corrupted"}
        )

        alerts = []
        if failed_count > 0 or snapshot_mismatches > 0:
            alerts.append({"severity": "HIGH", "message": "Integrity mismatch or corrupted evidence detected."})
        if unresolved_mapping > 0:
            alerts.append({"severity": "MEDIUM", "message": "Canonical degradation or unresolved mappings detected."})
        if drift_count > 0 and not alerts:
            alerts.append({"severity": "LOW", "message": "Schema drift detected; integrity still recoverable."})

        payload = {
            "session_id": session_id,
            "workflow_mode": mode,
            "metrics": {
                "verified_artifacts": verified_count,
                "integrity_failures": failed_count,
                "schema_drift_events": drift_count,
                "orphaned_traces": orphaned_traces,
                "snapshot_mismatches": snapshot_mismatches,
                "unresolved_canonical_mappings": unresolved_mapping,
                "corrupted_exports": corrupted_exports,
            },
            "alerts": alerts,
        }
        return self._shape_view_payload(payload, mode)

    def build_execution_trust_record(self, *, session_id: str, execution_id: str) -> dict:
        self._require_session(session_id)
        execution = self.db.get_model_execution(execution_id=execution_id)
        if not execution or execution.get("session_id") != session_id:
            raise PlaygroundError(f"Unknown execution_id '{execution_id}' for session '{session_id}'")

        raw_row = self.db.get_raw_evidence_by_execution(execution_id=execution_id)
        trace_row = self.db.get_canonical_trace_by_execution(execution_id=execution_id)
        if not raw_row or not trace_row:
            raise PlaygroundError(f"Execution '{execution_id}' is missing raw or canonical artifacts")

        raw_integrity = self.db.get_artifact_integrity(raw_row["id"], "raw_evidence")
        canonical_integrity = self.db.get_artifact_integrity(trace_row["id"], "canonical_trace")
        snapshot_rows = [row for row in self.db.list_snapshots(session_id=session_id) if row.get("execution_id") == execution_id]
        snapshot_row = snapshot_rows[0] if snapshot_rows else None
        snapshot_trust = self.build_snapshot_trust_summary(session_id=session_id, snapshot_id=snapshot_row["snapshot_id"]) if snapshot_row else None

        manifest_rows = self.db.list_transformation_manifests(session_id=session_id, execution_id=execution_id)
        manifest = self._decode_manifest_row(manifest_rows[0]) if manifest_rows else None
        custody = self.db.list_chain_of_custody_for_artifacts([execution_id, raw_row["id"], trace_row["id"]])

        trace_warnings = self._decode_json(trace_row.get("normalization_warnings_json"), [])
        trust_status = self._map_execution_integrity_status(
            raw_integrity=raw_integrity,
            canonical_integrity=canonical_integrity,
            trace_warnings=trace_warnings,
            snapshot_trust=snapshot_trust,
        )

        return {
            "session_id": session_id,
            "execution_id": execution_id,
            "integrity_status": trust_status,
            "acquisition_metadata": {
                "acquired_at": raw_row.get("collected_at_utc"),
                "provider_request_id": raw_row.get("request_id"),
                "provider_model": execution.get("model_id"),
                "runtime_version": "playground_runtime/current",
                "schema_version": trace_row.get("schema_version"),
            },
            "integrity_metadata": {
                "raw_sha256": raw_row.get("raw_sha256"),
                "canonical_sha256": canonical_integrity.get("sha256") if canonical_integrity else None,
                "snapshot_hash": snapshot_row.get("snapshot_hash") if snapshot_row else None,
                "export_hash": None,
                "verification_timestamp": canonical_integrity.get("created_at") if canonical_integrity else None,
            },
            "transformation_metadata": {
                "normalization_version": trace_row.get("schema_version"),
                "mapping_confidence": manifest.get("mapping_confidence") if manifest else None,
                "semantic_loss_flags": manifest.get("semantic_loss_flags_json") if manifest else [],
                "provider_alias_mapping": manifest.get("provider_alias_mapping_json") if manifest else {},
                "canonicalization_warnings": trace_warnings,
            },
            "provenance_metadata": {
                "execution_lineage": execution,
                "session_lineage": self.db.get_session(session_id),
                "export_lineage": self.db.list_forensic_reports(session_id=session_id),
                "replay_lineage": self.db.list_reproducibility_records(session_id=session_id),
                "custody_events": custody,
            },
            "snapshot_trust": snapshot_trust,
        }

    def build_snapshot_trust_summary(self, *, session_id: str, snapshot_id: str) -> dict:
        self._require_session(session_id)
        row = self.db.get_snapshot(snapshot_id)
        if not row or row.get("session_id") != session_id:
            raise PlaygroundError(f"Unknown snapshot_id '{snapshot_id}' for session '{session_id}'")
        status_raw = str(row.get("verification_status") or "unverified").lower()
        bundle = self._decode_json(row.get("snapshot_bundle_json"), {})
        manifest_rows = bundle.get("transformation_manifests", []) if isinstance(bundle, dict) else []
        runtime_config = bundle.get("runtime_config", {}) if isinstance(bundle, dict) else {}
        schema_versions = {
            item.get("schema_version")
            for item in bundle.get("canonical_traces", [])
            if isinstance(item, dict) and item.get("schema_version")
        } if isinstance(bundle, dict) else set()

        replay = "YES"
        if status_raw in {"failed", "corrupted"}:
            replay = "NO"
        elif status_raw in {"unverified"} or len(schema_versions) > 1:
            replay = "LIMITED"

        status_map = {
            "verified": "VALID",
            "failed": "CORRUPTED",
            "corrupted": "CORRUPTED",
            "unverified": "UNVERIFIED",
            "partial": "PARTIAL",
            "drifted": "DRIFTED",
        }
        trust_status = status_map.get(status_raw, "PARTIAL")
        if trust_status == "VALID":
            for manifest in manifest_rows:
                drift_flags = manifest.get("schema_drift_flags_json") or manifest.get("schema_drift_flags") or []
                if drift_flags:
                    trust_status = "DRIFTED"
                    if replay == "YES":
                        replay = "LIMITED"
                    break

        summary = {
            "snapshot_id": snapshot_id,
            "snapshot_hash": row.get("snapshot_hash"),
            "snapshot_integrity": trust_status,
            "provider_schema": ",".join(sorted(schema_versions)) if schema_versions else "unknown",
            "transformation_version": manifest_rows[0].get("transformer_version") if manifest_rows else "unknown",
            "replay_compatibility": replay,
            "verified_at": row.get("verified_at"),
            "runtime_mode": runtime_config.get("selected_mode") or runtime_config.get("mode"),
        }
        summary["summary_text"] = self._build_snapshot_trust_text(summary)
        return summary

    def build_session_timeline_integrity(self, *, session_id: str, actor: Optional[str] = None) -> dict:
        session = self._require_session(session_id)
        executions = self.db.list_model_executions(session_id=session_id)
        traces = self.db.list_canonical_traces(session_id=session_id)
        manifests = self.db.list_transformation_manifests(session_id=session_id)

        trace_by_execution = {row.get("execution_id"): row for row in traces}
        manifest_by_execution: dict[str, list[dict]] = {}
        for row in manifests:
            key = str(row.get("execution_id") or "")
            manifest_by_execution.setdefault(key, []).append(row)

        timeline_rows: list[dict] = []
        for execution in executions:
            execution_id = execution.get("id")
            trace = trace_by_execution.get(execution_id, {})
            manifest_rows = manifest_by_execution.get(str(execution_id), [])
            manifest_hashes = [row.get("target_hash") for row in manifest_rows if row.get("target_hash")]
            timeline_rows.append(
                {
                    "execution_id": execution_id,
                    "provider_id": execution.get("provider_id"),
                    "created_at_utc": execution.get("created_at_utc"),
                    "trace_id": trace.get("id"),
                    "forensic_flags": self._decode_json(trace.get("forensic_flags_json"), []),
                    "manifest_hashes": manifest_hashes,
                }
            )

        integrity_hash = sha256_json(timeline_rows)
        status = "VERIFIED"
        if not timeline_rows:
            status = "UNVERIFIED"

        existing = self.db.get_artifact_integrity(session_id, "session_timeline")
        self.db.update_session_integrity(session_id, integrity_hash, status.lower())
        existing_hash = (existing or {}).get("sha256")
        if existing_hash != integrity_hash:
            self.db.insert_artifact_integrity(
                artifact_id=session_id,
                artifact_type="session_timeline",
                sha256_value=integrity_hash,
                acquisition_session=session_id,
                verification_status="verified" if status == "VERIFIED" else "unverified",
            )
            self._record_custody_event(
                build_custody_event(
                    artifact_id=session_id,
                    action_type="SESSION_TIMELINE_HASHED",
                    actor=actor,
                    previous_hash=existing_hash,
                    new_hash=integrity_hash,
                    notes=f"rows={len(timeline_rows)}",
                )
            )
        session_updated = self.db.get_session(session_id) or session
        return {
            "session_id": session_id,
            "session_integrity_hash": integrity_hash,
            "session_integrity_status": status,
            "session_integrity_verified_at": session_updated.get("session_integrity_verified_at"),
            "timeline_rows": timeline_rows,
        }

    def build_transformation_lineage(self, *, session_id: str) -> dict:
        self._require_session(session_id)
        manifests = [self._decode_manifest_row(row) for row in self.db.list_transformation_manifests(session_id=session_id)]
        nodes = []
        edges = []
        for row in manifests:
            execution_id = row.get("execution_id")
            raw_node = f"raw:{row.get('source_artifact_id')}"
            candidate_node = f"candidate:{execution_id}"
            normalize_node = f"normalize:{execution_id}"
            canonical_node = f"canonical:{row.get('target_artifact_id')}"
            ontology_node = f"ontology:{execution_id}"
            summary_node = f"summary:{execution_id}"
            nodes.extend(
                [
                    {"id": raw_node, "label": "Raw Provider Artifact"},
                    {"id": candidate_node, "label": "Canonical Candidate Layer"},
                    {"id": normalize_node, "label": "Normalization Engine"},
                    {"id": canonical_node, "label": "Canonical Trace"},
                    {"id": ontology_node, "label": "Ontology Reconstruction"},
                    {"id": summary_node, "label": "Forensic Summary"},
                ]
            )
            edges.extend(
                [
                    {"source": raw_node, "target": candidate_node, "hash_state": row.get("source_hash"), "mapping_confidence": row.get("mapping_confidence")},
                    {"source": candidate_node, "target": normalize_node, "hash_state": row.get("source_hash"), "schema_drift_flags": row.get("schema_drift_flags_json")},
                    {"source": normalize_node, "target": canonical_node, "hash_state": row.get("target_hash"), "semantic_loss_flags": row.get("semantic_loss_flags_json")},
                    {"source": canonical_node, "target": ontology_node, "hash_state": row.get("target_hash")},
                    {"source": ontology_node, "target": summary_node, "hash_state": row.get("target_hash")},
                ]
            )

        # deduplicate nodes by id
        unique_nodes: dict[str, dict] = {}
        for node in nodes:
            unique_nodes[str(node["id"])] = node
        return {
            "session_id": session_id,
            "nodes": list(unique_nodes.values()),
            "edges": edges,
        }

    def export_forensic_bundle(
        self,
        *,
        session_id: str,
        output_path: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> dict:
        session = self._require_session(session_id)
        timeline = self.build_session_timeline_integrity(session_id=session_id, actor=actor)
        snapshots = self.db.list_snapshots(session_id=session_id)
        snapshot_summary = {"snapshot_integrity": "UNVERIFIED", "replay_compatibility": "LIMITED"}
        if snapshots:
            snapshot_summary = self.build_snapshot_trust_summary(session_id=session_id, snapshot_id=snapshots[0]["snapshot_id"])
        trust_notes = self._build_integrity_explanation(
            integrity_overview=self.build_integrity_overview(session_id=session_id, workflow_mode="academic"),
            snapshot_trust=snapshot_summary,
            workflow_mode="academic",
        )

        ontology_graphs = self.db.list_ontology_graphs(session_id=session_id)
        minimal_graphs = self._build_minimal_ontology_graphs(session_id=session_id)
        ontology_payload = {
            "graphs": ontology_graphs,
            "minimal_graphs": minimal_graphs,
            "entities": [],
            "relationships": [],
            "mappings": [],
        }
        if ontology_graphs:
            graph_id = ontology_graphs[0].get("id")
            ontology_payload["entities"] = self.db.list_ontology_entities(graph_id)
            ontology_payload["relationships"] = self.db.list_ontology_relationships(graph_id)
            ontology_payload["mappings"] = self.db.list_ontology_mappings(session_id)

        bundle_payload = {
            "session_id": session_id,
            "created_at": datetime.utcnow().isoformat(),
            "raw": [self._decode_raw_evidence_row(row) for row in self.db.list_raw_evidence(session_id=session_id)],
            "canonical": [self._decode_canonical_trace_row(row) for row in self.db.list_canonical_traces(session_id=session_id)],
            "manifests": [self._decode_manifest_row(row) for row in self.db.list_transformation_manifests(session_id=session_id)],
            "hashes": self.db.list_artifact_integrity(session_id=session_id),
            "custody": self.db.list_chain_of_custody_for_artifacts(
                [session_id]
                + [row.get("id") for row in self.db.list_model_executions(session_id=session_id)]
            ),
            "ontology": ontology_payload,
            "reports": self.db.list_forensic_reports(session_id=session_id),
            "trust_summary": {
                "session_integrity": timeline.get("session_integrity_status", "UNVERIFIED"),
                "snapshot_status": snapshot_summary.get("snapshot_integrity", "UNVERIFIED"),
                "replay_compatibility": snapshot_summary.get("replay_compatibility", "LIMITED"),
                "notes": trust_notes.splitlines(),
            },
        }
        exported = self.bundle_exporter.export_bundle(session_id=session_id, bundle_payload=bundle_payload, output_path=output_path)
        self.db.insert_artifact_integrity(
            artifact_id=exported["bundle_path"],
            artifact_type="forensic_bundle_zip",
            sha256_value=exported["bundle_sha256"],
            acquisition_session=session_id,
            verification_status="verified",
        )
        self._record_custody_event(
            build_custody_event(
                artifact_id=session_id,
                action_type="FORENSIC_BUNDLE_EXPORTED",
                actor=actor,
                new_hash=exported["bundle_sha256"],
                notes=exported["bundle_path"],
            )
        )
        self._update_runtime_config_state(
            session_id=session_id,
            source="runtime_profile",
            selected_mode=session.get("mode", "research"),
            effective_features={
                "report_export_enabled": True,
                "ontology_graph_enabled": bool(minimal_graphs or ontology_graphs),
            },
        )
        return {
            "session_id": session_id,
            "bundle": exported,
            "trust_summary": bundle_payload["trust_summary"],
        }

    def execute_dataset(
        self,
        *,
        session_id: str,
        provider_ids: list[str],
        mode: str,
        dataset_items: list[dict],
        execution_config: dict,
        actor: Optional[str] = None,
    ) -> dict:
        session = self._require_session(session_id)
        dataset_payload = {"dataset_items": dataset_items, "mode": mode}
        dataset_hash = sha256_json(dataset_payload)
        exec_cfg_hash = sha256_json({"provider_ids": provider_ids, "execution_config": execution_config})
        dataset_version = None
        if dataset_items:
            dataset_version = dataset_items[0].get("dataset_version")
        dataset_execution_id = self.db.insert_dataset_execution(
            session_id=session_id,
            dataset_hash=dataset_hash,
            dataset_version=dataset_version,
            provider_set_json=provider_ids,
            execution_config_hash=exec_cfg_hash,
            item_count=len(dataset_items),
            status="running",
        )
        result_rows: list[dict] = []
        for item in dataset_items:
            prompt = str(item.get("prompt", "")).strip()
            if not prompt:
                continue
            data_version = item.get("dataset_version")
            metadata = item.get("metadata", {})
            if len(provider_ids) > 1:
                row = self.execute_comparative(
                    session_id=session_id,
                    provider_ids=provider_ids,
                    prompt=prompt,
                    dataset_version=data_version,
                    metadata=metadata,
                    actor=actor,
                )
            else:
                row = self.execute_single(
                    session_id=session_id,
                    provider_id=provider_ids[0],
                    prompt=prompt,
                    dataset_version=data_version,
                    metadata=metadata,
                    actor=actor,
                )
            result_rows.append(row)
        summary = {
            "dataset_execution_id": dataset_execution_id,
            "session_id": session_id,
            "mode": session["mode"],
            "dataset_hash": dataset_hash,
            "provider_ids": provider_ids,
            "item_count": len(dataset_items),
            "completed_count": len(result_rows),
        }
        self.db.update_dataset_execution(dataset_execution_id, "completed", summary)
        self._record_custody_event(
            build_custody_event(
                artifact_id=dataset_execution_id,
                action_type="REPROCESSING",
                actor=actor,
                notes=f"dataset_items={len(dataset_items)}",
            )
        )
        return {"summary": summary, "results": result_rows}

    def _require_session(self, session_id: str) -> dict:
        session = self.db.get_session(session_id)
        if not session:
            raise PlaygroundError(f"Unknown session_id '{session_id}'")
        return session

    def _record_custody_event(self, payload: dict) -> None:
        self.db.insert_chain_of_custody(
            artifact_id=payload["artifact_id"],
            action_type=payload["action_type"],
            actor=payload["actor"],
            previous_hash=payload.get("previous_hash"),
            new_hash=payload.get("new_hash"),
            notes=payload.get("notes", ""),
        )

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
        actor: Optional[str] = None,
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
        self._record_custody_event(
            build_custody_event(
                artifact_id=execution_id,
                action_type="EXECUTION_CREATED",
                actor=actor,
                notes=f"provider={response.provider_id}",
            )
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
        raw_row = self.db.get_raw_evidence_by_id(raw_id) or {}
        raw_sha = str(raw_row.get("raw_sha256") or sha256_json(response.raw_json))
        self.db.insert_artifact_integrity(
            artifact_id=raw_id,
            artifact_type="raw_evidence",
            sha256_value=raw_sha,
            provider=response.provider_id,
            schema_version="provider_raw/1.0",
            acquisition_session=session_id,
            verification_status="verified",
        )
        self._record_custody_event(
            build_custody_event(
                artifact_id=raw_id,
                action_type="RAW_PERSISTED",
                actor=actor,
                new_hash=raw_sha,
                notes=f"execution_id={execution_id}",
            )
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
            metadata_aliases = {
                "system_fingerprint": "system_fingerprint",
                "id": "provider_response_id",
                "object": "provider_response_object",
                "created": "provider_response_created",
                "model": "provider_response_model",
            }
            for raw_key, canonical_key in metadata_aliases.items():
                if raw_key in response.raw_json:
                    normalized_input[canonical_key] = response.raw_json.get(raw_key)

            raw_choices = response.raw_json.get("choices")
            if isinstance(raw_choices, list) and raw_choices:
                first_choice = raw_choices[0] if isinstance(raw_choices[0], dict) else {}
                message = first_choice.get("message") if isinstance(first_choice, dict) else {}
                if isinstance(message, dict):
                    reasoning_artifact = message.get("reasoning")
                    if reasoning_artifact is not None:
                        normalized_input["visible_reasoning_trace"] = reasoning_artifact
                        normalized_input["visible_reasoning_trace_origin"] = "model_generated_artifact"
                        normalized_input["provider_specific_artifact_type"] = "visible_reasoning_trace"
                        normalized_input["provider_specific_artifact_origin"] = "model_generated_artifact"
                        normalized_input["provider_specific_artifact_human_readable"] = True

                    extra_content = message.get("extra_content")
                    if isinstance(extra_content, dict):
                        google_meta = extra_content.get("google")
                        if isinstance(google_meta, dict):
                            thought_signature = google_meta.get("thought_signature")
                            if thought_signature is not None:
                                normalized_input["provider_thought_signature"] = thought_signature
                                normalized_input["reasoning_signature_origin"] = "provider_opaque_artifact"
                                normalized_input["provider_specific_artifact_type"] = "opaque_reasoning_signature"
                                normalized_input["provider_specific_artifact_origin"] = "provider_opaque_artifact"
                                normalized_input["provider_specific_artifact_human_readable"] = False

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
        canonical_payload = self._decode_canonical_trace_row(self.db.get_canonical_trace_by_id(trace.trace_id) or {})
        canonical_hash = sha256_json(canonical_payload)
        self.db.insert_artifact_integrity(
            artifact_id=trace.trace_id,
            artifact_type="canonical_trace",
            sha256_value=canonical_hash,
            provider=trace.provider_id,
            schema_version=trace.schema_version,
            acquisition_session=session_id,
            verification_status="verified",
        )
        manifest = build_transformation_manifest(
            source_hash=raw_sha,
            target_hash=canonical_hash,
            transformer_version=trace.schema_version,
            raw_record=normalized_input,
            trace=trace,
        )
        self.db.insert_transformation_manifest(
            session_id=session_id,
            execution_id=execution_id,
            source_artifact_id=raw_id,
            target_artifact_id=trace.trace_id,
            manifest=manifest,
        )
        self._record_custody_event(
            build_custody_event(
                artifact_id=trace.trace_id,
                action_type="CANONICAL_CREATED",
                actor=actor,
                previous_hash=raw_sha,
                new_hash=canonical_hash,
                notes=f"execution_id={execution_id}",
            )
        )

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

    @staticmethod
    def _advisor_provider_environment(provider_id: Any) -> str:
        provider = str(provider_id or "").strip().lower()
        if provider == "ollama":
            return "local"
        if provider in {"gemini", "openai", "anthropic", "deepseek"}:
            return "cloud"
        return "unknown"

    @staticmethod
    def _advisor_has_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return bool(value)

    @staticmethod
    def _advisor_response_preview(text: Any, limit: int = 240) -> str:
        normalized = " ".join(str(text or "").split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 3)].rstrip() + "..."

    def _decode_raw_evidence_row(self, row: dict) -> dict:
        return {
            **row,
            "raw_json": self._decode_json(row.get("raw_json"), {}),
        }

    def _decode_canonical_trace_row(self, row: dict) -> dict:
        if not row:
            return {}
        return {
            **row,
            "grounding_chunks_json": self._decode_json(row.get("grounding_chunks_json"), []),
            "citation_objects_json": self._decode_json(row.get("citation_objects_json"), []),
            "safety_ratings_json": self._decode_json(row.get("safety_ratings_json"), None),
            "forensic_flags_json": self._decode_json(row.get("forensic_flags_json"), []),
            "normalization_warnings_json": self._decode_json(row.get("normalization_warnings_json"), []),
            "extra_fields_json": self._decode_json(row.get("extra_fields_json"), {}),
        }

    def _decode_manifest_row(self, row: dict) -> dict:
        return {
            **row,
            "semantic_loss_flags_json": self._decode_json(row.get("semantic_loss_flags_json"), []),
            "schema_drift_flags_json": self._decode_json(row.get("schema_drift_flags_json"), []),
            "canonical_candidates_json": self._decode_json(row.get("canonical_candidates_json"), []),
            "provider_alias_mapping_json": self._decode_json(row.get("provider_alias_mapping_json"), {}),
        }

    def _decode_capability_row(self, row: dict) -> dict:
        return {
            **row,
            "capability_json": self._decode_json(row.get("capability_json"), {}),
        }

    def _decode_semantic_divergence_row(self, row: dict) -> dict:
        variance = self._decode_json(row.get("provider_variance_json"), {})
        if not isinstance(variance, dict):
            variance = {}
        return {
            **row,
            "contradiction_flags_json": self._decode_json(row.get("contradiction_flags_json"), []),
            "provider_variance_json": variance,
            "classification_label_left": variance.get("classification_label_left"),
            "classification_label_right": variance.get("classification_label_right"),
            "classification_agreement": variance.get("classification_agreement"),
            "rationale_overlap": variance.get("rationale_overlap"),
            "output_length_delta": variance.get("output_length_delta"),
            "token_delta": variance.get("token_delta"),
            "latency_delta_ms": variance.get("latency_delta_ms"),
            "metadata_surface_delta": variance.get("metadata_surface_delta"),
            "visible_reasoning_delta": variance.get("visible_reasoning_delta"),
            "provider_specific_artifact_delta": variance.get("provider_specific_artifact_delta"),
            "contradiction_detected": variance.get("contradiction_detected"),
        }

    @staticmethod
    def _build_forensic_narrative(history: dict, divergence_rows: list[dict]) -> str:
        providers = {row.get("provider_id", "unknown") for row in history.get("executions", [])}
        trace_count = history.get("traces_summary", {}).get("count", 0)
        if not providers:
            return "No execution evidence has been recorded for this session."
        provider_list = ", ".join(sorted(providers))
        if not divergence_rows:
            return f"Session contains {trace_count} trace(s) from provider(s): {provider_list}. Divergence data is not available yet."
        return (
            f"Session contains {trace_count} trace(s) from provider(s): {provider_list}. "
            f"Observed {len(divergence_rows)} semantic divergence pair(s) across provider outputs."
        )

    def _update_runtime_config_state(
        self,
        *,
        session_id: str,
        source: str,
        selected_mode: Optional[str] = None,
        effective_workflow_mode: Optional[str] = None,
        ui_selected_providers: Optional[list[str]] = None,
        provider_count: Optional[int] = None,
        effective_features: Optional[dict[str, bool]] = None,
    ) -> None:
        runtime_rows = self.db.list_runtime_configs(session_id=session_id)
        if not runtime_rows:
            return
        latest = self._decode_json(runtime_rows[0].get("config_json"), {}) if runtime_rows else {}
        if not isinstance(latest, dict):
            latest = {}
        updated = deepcopy(latest)

        if selected_mode:
            updated["selected_mode"] = selected_mode
        if effective_workflow_mode:
            updated["effective_workflow_mode"] = effective_workflow_mode
        if ui_selected_providers is not None:
            providers = [str(p).strip() for p in ui_selected_providers if str(p).strip()]
            updated["ui_selected_providers"] = providers
            updated["provider_count"] = len(providers)
        elif provider_count is not None:
            updated["provider_count"] = int(max(provider_count, 0))

        env_flags = updated.get("env_feature_flags")
        if not isinstance(env_flags, dict):
            env_flags = updated.get("flags")
        if not isinstance(env_flags, dict):
            env_flags = self.settings.snapshot_flags()
        updated["env_feature_flags"] = env_flags

        feature_state = updated.get("effective_features")
        if not isinstance(feature_state, dict):
            feature_state = {}
        feature_defaults = {
            "comparative_execution_enabled": bool(updated.get("comparative_execution_enabled", False)),
            "forensic_integrity_enabled": bool(updated.get("forensic_integrity_enabled", False)),
            "ontology_graph_enabled": bool(updated.get("ontology_graph_enabled", False)),
            "report_export_enabled": bool(updated.get("report_export_enabled", False)),
        }
        merged_features = {**feature_defaults, **feature_state}
        if isinstance(effective_features, dict):
            merged_features.update({k: bool(v) for k, v in effective_features.items()})
        updated["effective_features"] = merged_features
        for key, value in merged_features.items():
            updated[key] = bool(value)

        sources = set()
        previous_sources = updated.get("feature_sources", [])
        if isinstance(previous_sources, list):
            sources.update(str(item) for item in previous_sources if str(item).strip())
        if source:
            sources.add(source)
        if selected_mode:
            sources.add("runtime_profile")
        if ui_selected_providers:
            sources.add("ui")

        env_mapping = {
            "comparative_execution_enabled": bool(env_flags.get("KURO_PLAYGROUND_COMPARATIVE_MODE", False)),
            "forensic_integrity_enabled": bool(env_flags.get("KURO_PLAYGROUND_FORENSIC_MODE", False)),
            "ontology_graph_enabled": bool(env_flags.get("KURO_PLAYGROUND_ONTOLOGY_MODE", False)),
            "report_export_enabled": bool(env_flags.get("KURO_PLAYGROUND_REPORT_EXPORT", False)),
        }
        if any(env_mapping.values()):
            sources.add("env")
        if any(merged_features.get(key, False) and not env_mapping.get(key, False) for key in env_mapping):
            sources.add("ui")

        if not sources:
            sources.add("runtime_profile")
        updated["feature_sources"] = sorted(sources)
        updated["feature_source"] = next(iter(sources)) if len(sources) == 1 else "mixed"

        self.db.insert_runtime_config(session_id=session_id, config=updated)

    def _build_minimal_ontology_graphs(self, *, session_id: str) -> list[dict]:
        traces = self.db.list_canonical_traces(session_id=session_id)
        if not traces:
            return []
        executions = {row.get("id"): row for row in self.db.list_model_executions(session_id=session_id)}
        raw_rows = {row.get("execution_id"): row for row in self.db.list_raw_evidence(session_id=session_id)}
        runtime_rows = self.db.list_runtime_configs(session_id=session_id)
        runtime_latest = self._decode_json(runtime_rows[0].get("config_json"), {}) if runtime_rows else {}

        graphs: list[dict] = []
        for trace_row in traces:
            trace = self._decode_canonical_trace_row(trace_row)
            trace_id = str(trace.get("id") or trace.get("trace_id") or "")
            execution_id = str(trace.get("execution_id") or "")
            if not trace_id:
                continue
            execution = executions.get(execution_id, {})
            raw = raw_rows.get(execution_id, {})
            raw_id = str(raw.get("id") or "")
            provider_id = str(trace.get("provider_id") or execution.get("provider_id") or "unknown")
            model_id = str(trace.get("model_id") or execution.get("model_id") or "unknown")
            prompt_sha = str(trace.get("prompt_sha256") or execution.get("prompt_sha256") or "unknown")
            response_text = str(trace.get("response_text") or "")
            raw_sha = str(raw.get("raw_sha256") or "")
            canonical_integrity = self.db.get_artifact_integrity(trace_id, "canonical_trace") or {}
            canonical_sha = str(canonical_integrity.get("sha256") or "")
            extra = trace.get("extra_fields_json")
            if not isinstance(extra, dict):
                extra = self._decode_json(trace.get("extra_fields_json"), {})
            if not isinstance(extra, dict):
                extra = {}

            nodes: list[dict] = []
            edges: list[dict] = []
            node_seen: set[str] = set()

            def add_node(node_id: str, **payload) -> None:
                if node_id in node_seen:
                    return
                node_seen.add(node_id)
                nodes.append({"id": node_id, **payload})

            def add_edge(source: str, target: str, edge_type: str) -> None:
                edges.append({"source": source, "target": target, "type": edge_type})

            trace_node = f"trace:{trace_id}"
            prompt_node = f"prompt:{prompt_sha}"
            provider_node = f"provider:{provider_id}"
            model_node = f"model:{model_id}"
            output_node = f"output:{trace_id}"
            raw_node = f"raw:{raw_id or execution_id or trace_id}"
            normalize_node = f"normalize:{execution_id or trace_id}"
            canonical_node = f"canonical:{trace_id}"
            usage_node = f"usage:{trace_id}"
            runtime_node = f"runtime:{session_id}:{execution_id or trace_id}"
            raw_hash_node = f"hash:raw:{raw_id or execution_id or trace_id}"
            canonical_hash_node = f"hash:canonical:{trace_id}"

            add_node(trace_node, type="AIInferenceTrace")
            add_node(prompt_node, type="PromptHash", sha256=prompt_sha)
            add_node(provider_node, type="Provider", name=provider_id)
            add_node(model_node, type="AIModel", model_id=model_id)
            add_node(output_node, type="ModelOutput", text_preview=response_text[:240])
            add_node(raw_node, type="RawProviderArtifact", artifact_id=raw_id, sha256=raw_sha or None)
            add_node(normalize_node, type="NormalizationProcess", schema_version=trace.get("schema_version"))
            add_node(canonical_node, type="CanonicalTrace", trace_id=trace_id, sha256=canonical_sha or None)
            add_node(raw_hash_node, type="EvidenceHash", sha256=raw_sha or "unknown")
            add_node(canonical_hash_node, type="EvidenceHash", sha256=canonical_sha or "unknown")
            add_node(
                usage_node,
                type="TokenUsage",
                input_tokens=trace.get("input_tokens"),
                output_tokens=trace.get("output_tokens"),
                total_tokens=trace.get("total_tokens"),
            )
            add_node(
                runtime_node,
                type="RuntimeMetadata",
                selected_mode=runtime_latest.get("selected_mode") or runtime_latest.get("mode"),
                effective_workflow_mode=runtime_latest.get("effective_workflow_mode"),
                feature_source=runtime_latest.get("feature_source"),
            )

            add_edge(trace_node, prompt_node, "hasPromptHash")
            add_edge(trace_node, provider_node, "generatedBy")
            add_edge(trace_node, model_node, "usedModel")
            add_edge(trace_node, output_node, "producedOutput")
            add_edge(trace_node, raw_node, "hasRawEvidence")
            add_edge(raw_node, normalize_node, "normalizedBy")
            add_edge(normalize_node, canonical_node, "produced")
            add_edge(raw_node, canonical_node, "normalizedInto")
            add_edge(raw_node, raw_hash_node, "hasIntegrityHash")
            add_edge(canonical_node, canonical_hash_node, "hasIntegrityHash")
            add_edge(trace_node, usage_node, "hasTokenUsage")
            add_edge(trace_node, runtime_node, "hasRuntimeMetadata")

            provider_artifact_node = None
            if extra.get("visible_reasoning_trace"):
                provider_artifact_node = f"provider_artifact:{trace_id}:visible_reasoning"
                add_node(
                    provider_artifact_node,
                    type="ProviderSpecificArtifact",
                    artifact_type="visible_reasoning_trace",
                    origin=extra.get("visible_reasoning_trace_origin", "model_generated_artifact"),
                    human_readable=True,
                )
            elif extra.get("provider_thought_signature"):
                provider_artifact_node = f"provider_artifact:{trace_id}:opaque_signature"
                add_node(
                    provider_artifact_node,
                    type="ProviderSpecificArtifact",
                    artifact_type="opaque_reasoning_signature",
                    origin=extra.get("reasoning_signature_origin", "provider_opaque_artifact"),
                    human_readable=False,
                )
            if provider_artifact_node:
                add_edge(trace_node, provider_artifact_node, "hasProviderSpecificArtifact")

            graphs.append(
                {
                    "graph_id": f"graph:{session_id}:{execution_id or trace_id}",
                    "session_id": session_id,
                    "execution_id": execution_id,
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "prompt_sha256": prompt_sha,
                    "graph_schema_version": "kuro-ontology-minimal/1.0.0",
                    "created_at_utc": trace.get("collected_at_utc"),
                    "nodes": nodes,
                    "edges": edges,
                }
            )
        return graphs

    def _ensure_runtime_config_consistency(
        self,
        *,
        runtime_config: dict,
        session_mode: str,
        executions: list[dict],
        reports: list[dict],
        ontology_graphs: list[dict],
    ) -> dict:
        config = deepcopy(runtime_config if isinstance(runtime_config, dict) else {})
        env_flags = config.get("env_feature_flags")
        if not isinstance(env_flags, dict):
            env_flags = config.get("flags")
        if not isinstance(env_flags, dict):
            env_flags = self.settings.snapshot_flags()
        config["env_feature_flags"] = env_flags

        provider_ids = sorted({str(row.get("provider_id")) for row in executions if row.get("provider_id")})
        provider_count = len(provider_ids)
        config["ui_selected_providers"] = config.get("ui_selected_providers") or provider_ids
        config["provider_count"] = int(config.get("provider_count") or provider_count)
        config["selected_mode"] = config.get("selected_mode") or config.get("mode") or session_mode

        default_workflow = "comparative" if provider_count > 1 else "quick"
        config["effective_workflow_mode"] = config.get("effective_workflow_mode") or default_workflow

        feature_state = config.get("effective_features")
        if not isinstance(feature_state, dict):
            feature_state = {}
        effective_features = {
            "comparative_execution_enabled": bool(
                feature_state.get("comparative_execution_enabled")
                or config.get("comparative_execution_enabled")
                or provider_count > 1
            ),
            "forensic_integrity_enabled": bool(
                feature_state.get("forensic_integrity_enabled")
                or config.get("forensic_integrity_enabled")
                or len(executions) > 0
            ),
            "ontology_graph_enabled": bool(
                feature_state.get("ontology_graph_enabled")
                or config.get("ontology_graph_enabled")
                or len(ontology_graphs) > 0
            ),
            "report_export_enabled": bool(
                feature_state.get("report_export_enabled")
                or config.get("report_export_enabled")
                or len(reports) > 0
            ),
        }
        config["effective_features"] = effective_features
        for key, value in effective_features.items():
            config[key] = value

        env_mapping = {
            "comparative_execution_enabled": bool(env_flags.get("KURO_PLAYGROUND_COMPARATIVE_MODE", False)),
            "forensic_integrity_enabled": bool(env_flags.get("KURO_PLAYGROUND_FORENSIC_MODE", False)),
            "ontology_graph_enabled": bool(env_flags.get("KURO_PLAYGROUND_ONTOLOGY_MODE", False)),
            "report_export_enabled": bool(env_flags.get("KURO_PLAYGROUND_REPORT_EXPORT", False)),
        }
        sources: set[str] = set()
        previous_sources = config.get("feature_sources", [])
        if isinstance(previous_sources, list):
            sources.update(str(item) for item in previous_sources if str(item).strip())
        sources.add("runtime_profile")
        if provider_count > 0:
            sources.add("ui")
        if any(env_mapping.values()):
            sources.add("env")
        if any(effective_features[key] and not env_mapping.get(key, False) for key in env_mapping):
            sources.add("ui")
        config["feature_sources"] = sorted(sources)
        config["feature_source"] = next(iter(sources)) if len(sources) == 1 else "mixed"
        return config

    @staticmethod
    def _normalize_workflow_mode(value: str) -> str:
        mode = (value or "quick").strip().lower()
        if mode not in {"quick", "deep", "academic"}:
            raise PlaygroundError("workflow_mode must be one of: quick, deep, academic")
        return mode

    def _shape_view_payload(self, payload: dict, mode: str) -> dict:
        shaped = {**payload, "workflow_mode": mode}
        if mode == "quick":
            return shaped
        if mode == "deep":
            shaped["rendering_hint"] = "deep_forensic"
            return shaped
        shaped["rendering_hint"] = "academic_presentation"
        return shaped

    def _map_execution_integrity_status(
        self,
        *,
        raw_integrity: dict | None,
        canonical_integrity: dict | None,
        trace_warnings: list,
        snapshot_trust: dict | None,
    ) -> str:
        raw_status = str((raw_integrity or {}).get("verification_status") or "unverified").lower()
        canonical_status = str((canonical_integrity or {}).get("verification_status") or "unverified").lower()
        if raw_status in {"failed", "corrupted"} or canonical_status in {"failed", "corrupted"}:
            return "CORRUPTED"
        if snapshot_trust and snapshot_trust.get("snapshot_integrity") == "CORRUPTED":
            return "CORRUPTED"
        if raw_status == "unverified" or canonical_status == "unverified":
            return "UNVERIFIED"
        if snapshot_trust and snapshot_trust.get("snapshot_integrity") == "PARTIAL":
            return "PARTIAL"
        if any(str(w).startswith("SCHEMA_DRIFT") for w in trace_warnings):
            return "DRIFTED"
        if snapshot_trust and snapshot_trust.get("snapshot_integrity") == "DRIFTED":
            return "MODIFIED"
        return "VERIFIED"

    @staticmethod
    def _build_snapshot_trust_text(summary: dict) -> str:
        status = summary.get("snapshot_integrity", "UNVERIFIED")
        replay = summary.get("replay_compatibility", "LIMITED")
        if status == "VALID":
            return f"Snapshot verification passed with status VALID; replay compatibility is {replay}."
        if status == "DRIFTED":
            return f"Snapshot is DRIFTED with recoverable lineage; replay compatibility is {replay}."
        if status == "PARTIAL":
            return f"Snapshot is PARTIAL because one or more integrity components are missing; replay compatibility is {replay}."
        if status == "CORRUPTED":
            return f"Snapshot is CORRUPTED due to integrity mismatch; replay compatibility is {replay}."
        return f"Snapshot has not been verified; replay compatibility is {replay}."

    def _compact_execution_trust(self, *, session_id: str, execution_id: str) -> dict:
        try:
            detail = self.build_execution_trust_record(session_id=session_id, execution_id=execution_id)
        except PlaygroundError:
            return {
                "execution_id": execution_id,
                "integrity_status": "UNVERIFIED",
                "raw_sha256": None,
                "canonical_sha256": None,
                "snapshot_state": "UNVERIFIED",
                "schema_drift_detected": False,
                "transformation_integrity_state": "PARTIAL",
            }
        transform_flags = detail.get("transformation_metadata", {}).get("semantic_loss_flags", [])
        warning_flags = detail.get("transformation_metadata", {}).get("canonicalization_warnings", [])
        snapshot = detail.get("snapshot_trust") or {}
        return {
            "execution_id": execution_id,
            "integrity_status": detail.get("integrity_status", "UNVERIFIED"),
            "raw_sha256": detail.get("integrity_metadata", {}).get("raw_sha256"),
            "canonical_sha256": detail.get("integrity_metadata", {}).get("canonical_sha256"),
            "snapshot_state": snapshot.get("snapshot_integrity", "UNVERIFIED"),
            "schema_drift_detected": any(str(w).startswith("SCHEMA_DRIFT") for w in warning_flags),
            "transformation_integrity_state": "PARTIAL" if transform_flags else "VALID",
        }

    def _build_integrity_explanation(self, *, integrity_overview: dict, snapshot_trust: dict, workflow_mode: str) -> str:
        metrics = integrity_overview.get("metrics", {})
        drift = int(metrics.get("schema_drift_events", 0) or 0)
        failed = int(metrics.get("integrity_failures", 0) or 0)
        replay = snapshot_trust.get("replay_compatibility", "LIMITED")
        lines = []
        if failed == 0:
            lines.append("The raw provider artifacts remain unchanged since acquisition.")
        else:
            lines.append("Integrity violations were detected in one or more artifacts.")
        if drift > 0:
            lines.append("Schema drift was detected but semantic preservation remains under active review.")
        else:
            lines.append("Canonical normalization completed without schema drift events.")
        lines.append(f"Replay compatibility is currently assessed as {replay}.")
        if workflow_mode == "quick":
            return " ".join(lines[:2])
        if workflow_mode == "deep":
            lines.append("This trust state distinguishes integrity, compatibility, and semantic similarity independently.")
            return "\n".join(lines)
        lines.append("No deterministic equivalence claim is made for probabilistic model outputs.")
        return "\n".join(lines)
