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
    ExecuteRequest,
    OntologyRequest,
    ReportRequest,
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
            )
        except ProviderExecutionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PlaygroundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/ontology/reconstruct")
    def reconstruct_ontology(payload: OntologyRequest, _user: dict = Depends(admin_dependency)):
        _guard_enabled()
        try:
            return service.reconstruct_ontology(session_id=payload.session_id)
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
            )
        except PlaygroundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
