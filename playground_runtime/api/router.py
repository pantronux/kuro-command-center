"""
Playground API router.

--- Header Doc ---
Purpose: Expose isolated KPR endpoints under /api/playground.
Caller: main.py conditional router mount.
Dependencies: fastapi, playground service/schemas/errors.
Main Functions: create_playground_router().
Side Effects: Calls runtime service and writes KPR DB.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from playground_runtime.api.schemas import (
    ComparativeExecuteRequest,
    CreateSessionRequest,
    DatasetExecutionRequest,
    ExecuteRequest,
    ForensicBundleExportRequest,
    ForensicViewRequest,
    IntegrityRefreshRequest,
    IntegrityOverviewRequest,
    OntologyRequest,
    ReportRequest,
    SnapshotRequest,
    SnapshotVerifyRequest,
)
from playground_runtime.errors import PlaygroundError, ProviderExecutionError
from playground_runtime.service import PlaygroundRuntimeService


def create_playground_router(
    service: PlaygroundRuntimeService,
    admin_dependency: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api/playground", tags=["playground-runtime"])

    def _guard_enabled() -> None:
        try:
            service.assert_api_enabled()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=f"Disabled: {exc}") from exc

    def _status_for_playground_error(exc: PlaygroundError, default_status: int = 400) -> int:
        msg = str(exc).lower()
        if "invalid session_id format" in msg or "artifact type must be one of" in msg:
            return 422
        if "required for execution_raw" in msg:
            return 422
        if "unknown session_id" in msg or "unknown execution_id" in msg:
            return 404
        if msg.startswith("no raw evidence found") or msg.startswith("no canonical trace found"):
            return 404
        return default_status

    @router.get("/health")
    def health(_user: dict = Depends(admin_dependency)):
        _guard_enabled()
        return service.health()

    @router.get("/providers")
    def list_providers(_user: dict = Depends(admin_dependency)):
        _guard_enabled()
        return {"providers": service.list_providers()}

    @router.post("/sessions")
    def create_session(payload: CreateSessionRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.create_session(
                mode=payload.mode,
                runtime_config_override=payload.runtime_config_override,
                session_id=payload.session_id,
                actor=_user.get("username", "system"),
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions")
    def list_sessions(
        limit: int = Query(default=20, ge=1, le=100),
        mode: str | None = Query(default=None),
        _user: dict = Depends(admin_dependency),
    ):
        _guard_enabled()
        return {"sessions": service.list_sessions(limit=limit, mode=mode)}

    @router.get("/sessions/latest")
    def latest_session(_user: dict = Depends(admin_dependency)):
        _guard_enabled()
        latest = service.get_latest_session()
        if not latest:
            raise HTTPException(status_code=404, detail="No playground sessions found")
        return latest

    @router.post("/executions")
    def execute(payload: ExecuteRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.execute_single(
                session_id=payload.session_id,
                provider_id=payload.provider_id,
                prompt=payload.prompt,
                dataset_version=payload.dataset_version,
                model_override=payload.model_override,
                metadata=payload.metadata,
                actor=_user.get("username", "system"),
            )
        except ProviderExecutionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PlaygroundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/comparative-executions")
    def execute_comparative(payload: ComparativeExecuteRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        if len(payload.provider_ids) < 2:
            raise HTTPException(status_code=422, detail="comparative execution requires at least 2 providers")
        try:
            return service.execute_comparative(
                session_id=payload.session_id,
                provider_ids=payload.provider_ids,
                prompt=payload.prompt,
                dataset_version=payload.dataset_version,
                metadata=payload.metadata,
                actor=_user.get("username", "system"),
            )
        except ProviderExecutionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PlaygroundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/ontology/reconstruct")
    def reconstruct_ontology(payload: OntologyRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.reconstruct_ontology(
                session_id=payload.session_id,
                actor=_user.get("username", "system"),
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/reports/{report_format}")
    def export_report(report_format: str, payload: ReportRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        report_format = report_format.lower().strip()
        if report_format not in {"json", "rdf", "csv"}:
            raise HTTPException(status_code=422, detail="report_format must be one of: json, rdf, csv")
        try:
            return service.build_and_export_report(
                session_id=payload.session_id,
                report_format=report_format,
                output_path=payload.output_path,
                actor=_user.get("username", "system"),
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/snapshots")
    def create_snapshot(payload: SnapshotRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.create_snapshot(
                session_id=payload.session_id,
                execution_id=payload.execution_id,
                actor=_user.get("username", "system"),
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.post("/snapshots/{snapshot_id}/verify")
    def verify_snapshot(snapshot_id: str, payload: SnapshotVerifyRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.verify_snapshot(
                session_id=payload.session_id,
                snapshot_id=snapshot_id,
                actor=_user.get("username", "system"),
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/forensic-view")
    def forensic_view(
        session_id: str,
        view: str = Query(default="summary"),
        workflow_mode: str = Query(default="quick"),
        _user: dict = Depends(admin_dependency),
    ):
        _guard_enabled()
        try:
            payload = ForensicViewRequest(session_id=session_id, view=view, workflow_mode=workflow_mode)
            return service.build_forensic_view(
                session_id=payload.session_id,
                view=payload.view,
                workflow_mode=payload.workflow_mode,
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/integrity-overview")
    def integrity_overview(
        session_id: str,
        workflow_mode: str = Query(default="quick"),
        _user: dict = Depends(admin_dependency),
    ):
        _guard_enabled()
        try:
            payload = IntegrityOverviewRequest(session_id=session_id, workflow_mode=workflow_mode)
            return service.build_integrity_overview(
                session_id=payload.session_id,
                workflow_mode=payload.workflow_mode,
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/advisor-context")
    def advisor_context(
        session_id: str,
        workflow_mode: str = Query(default="quick"),
        _user: dict = Depends(admin_dependency),
    ):
        _guard_enabled()
        try:
            return service.build_advisor_context(
                session_id=session_id,
                workflow_mode=workflow_mode,
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/executions/{execution_id}/integrity-detail")
    def execution_integrity_detail(session_id: str, execution_id: str, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.build_execution_trust_record(session_id=session_id, execution_id=execution_id)
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.post("/sessions/{session_id}/integrity/refresh")
    def refresh_integrity(
        session_id: str,
        payload: IntegrityRefreshRequest | None = None,
        _user: dict = Depends(admin_dependency),
    ):
        _guard_enabled()
        try:
            payload = payload or IntegrityRefreshRequest()
            timeline = service.build_session_timeline_integrity(
                session_id=session_id,
                actor=_user.get("username", "system"),
            )
            overview = service.build_integrity_overview(
                session_id=session_id,
                workflow_mode=payload.workflow_mode,
            )
            return {"timeline": timeline, "overview": overview}
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/snapshots/{snapshot_id}/trust-summary")
    def snapshot_trust_summary(
        snapshot_id: str,
        session_id: str = Query(...),
        _user: dict = Depends(admin_dependency),
    ):
        _guard_enabled()
        try:
            return service.build_snapshot_trust_summary(session_id=session_id, snapshot_id=snapshot_id)
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.post("/sessions/{session_id}/exports/forensic-bundle")
    def export_forensic_bundle(
        session_id: str,
        payload: ForensicBundleExportRequest,
        _user: dict = Depends(admin_dependency),
    ):
        _guard_enabled()
        try:
            return service.export_forensic_bundle(
                session_id=session_id,
                output_path=payload.output_path,
                actor=_user.get("username", "system"),
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/lineage")
    def lineage(session_id: str, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.build_transformation_lineage(session_id=session_id)
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.post("/datasets/executions")
    def execute_dataset(payload: DatasetExecutionRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        if not payload.provider_ids:
            raise HTTPException(status_code=422, detail="provider_ids must not be empty")
        if not payload.dataset_items:
            raise HTTPException(status_code=422, detail="dataset_items must not be empty")
        try:
            return service.execute_dataset(
                session_id=payload.session_id,
                provider_ids=payload.provider_ids,
                mode=payload.mode,
                dataset_items=[
                    item.model_dump() if hasattr(item, "model_dump") else item.dict()  # pydantic v2/v1 compat
                    for item in payload.dataset_items
                ],
                execution_config=payload.execution_config,
                actor=_user.get("username", "system"),
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/traces")
    def list_traces(session_id: str, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return {"traces": service.list_session_traces(session_id=session_id)}
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/history")
    def session_history(session_id: str, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.get_session_history(session_id=session_id)
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/artifacts/json")
    def session_artifact_json(
        session_id: str,
        type: str = Query(...),
        execution_id: str | None = Query(default=None),
        _user: dict = Depends(admin_dependency),
    ):
        _guard_enabled()
        try:
            filename, payload = service.build_session_json_artifact(
                session_id=session_id,
                artifact_type=type,
                execution_id=execution_id,
            )
            return Response(
                content=payload,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=_status_for_playground_error(exc), detail=str(exc)) from exc

    return router
