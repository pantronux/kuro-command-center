"""FastAPI routes for the KRC approved knowledge gateway."""
from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from kuro_backend.knowledge_center.approved_search import (
    build_approved_context,
    search_approved_knowledge,
)
from kuro_backend.knowledge_center.audit import log_knowledge_access
from kuro_backend.knowledge_center.candidates import KnowledgeStore
from kuro_backend.knowledge_center.policy import (
    candidate_writes_enabled,
    resolve_knowledge_actor,
)
from kuro_backend.knowledge_center.schemas import (
    CandidateDecisionRequest,
    CandidateKnowledgeRequest,
    KnowledgeContextRequest,
    KnowledgeIngestRequest,
    KnowledgeSearchRequest,
)


def _trace_id(request: Request) -> str:
    return str(getattr(request.state, "trace_id", "") or "")


def create_knowledge_router(
    *,
    cookie_auth_dependency: Callable[[Request], Dict[str, str]],
    admin_dependency: Callable[[Request], Dict[str, str]],
) -> APIRouter:
    router = APIRouter()

    def _store() -> KnowledgeStore:
        return KnowledgeStore()

    def _actor(request: Request) -> Dict[str, Any]:
        return resolve_knowledge_actor(
            request,
            cookie_auth_dependency=cookie_auth_dependency,
        )

    @router.get("/api/knowledge/health")
    async def knowledge_health() -> Dict[str, Any]:
        store = _store()
        return {
            "status": "ok",
            "approved_only": True,
            "candidate_writes_enabled": candidate_writes_enabled(),
            "approved_count": store.approved_count(),
            "pending_candidate_count": store.candidate_count("pending"),
        }

    @router.post("/api/knowledge/search-approved")
    async def knowledge_search_approved(
        payload: KnowledgeSearchRequest,
        request: Request,
        actor: Dict[str, Any] = Depends(_actor),
    ) -> Dict[str, Any]:
        store = _store()
        trace_id = _trace_id(request)
        log_knowledge_access(store, actor=actor, action="search-approved", trace_id=trace_id)
        return {
            "results": search_approved_knowledge(
                store=store,
                query=payload.query,
                domains=payload.domains,
                limit=payload.limit,
            ),
            "trace_id": trace_id,
        }

    @router.post("/api/knowledge/context-approved")
    async def knowledge_context_approved(
        payload: KnowledgeContextRequest,
        request: Request,
        actor: Dict[str, Any] = Depends(_actor),
    ) -> Dict[str, Any]:
        store = _store()
        trace_id = _trace_id(request)
        log_knowledge_access(store, actor=actor, action="context-approved", trace_id=trace_id)
        context = build_approved_context(
            store=store,
            query=payload.query,
            domains=payload.domains,
            limit=payload.limit,
            max_chars=payload.max_chars,
        )
        context["trace_id"] = trace_id
        return context

    @router.post("/api/knowledge/candidates")
    async def knowledge_submit_candidate(
        payload: CandidateKnowledgeRequest,
        request: Request,
        actor: Dict[str, Any] = Depends(_actor),
    ) -> Dict[str, Any]:
        if not candidate_writes_enabled():
            raise HTTPException(status_code=403, detail="Candidate knowledge writes are disabled.")
        store = _store()
        trace_id = _trace_id(request)
        candidate = store.create_candidate(payload)
        log_knowledge_access(store, actor=actor, action="candidate-submit", trace_id=trace_id)
        return {
            "candidate_id": candidate["candidate_id"],
            "status": candidate["status"],
            "canonical": False,
            "trace_id": trace_id,
        }

    @router.get("/api/knowledge/sources/{source_id}")
    async def knowledge_source_metadata(
        source_id: str,
        request: Request,
        actor: Dict[str, Any] = Depends(_actor),
    ) -> Dict[str, Any]:
        store = _store()
        trace_id = _trace_id(request)
        source = store.source_metadata(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Approved source not found.")
        log_knowledge_access(store, actor=actor, action="source-read", trace_id=trace_id)
        return {"source": source, "trace_id": trace_id}

    @router.post("/api/knowledge/ingest")
    async def knowledge_ingest(
        payload: KnowledgeIngestRequest,
        request: Request,
        actor: Dict[str, Any] = Depends(_actor),
    ) -> Dict[str, Any]:
        store = _store()
        trace_id = _trace_id(request)
        job = store.create_ingest_job(payload)
        log_knowledge_access(store, actor=actor, action="ingest-submit", trace_id=trace_id)
        return {"job": job, "trace_id": trace_id}

    @router.get("/api/knowledge/ingest/jobs")
    async def knowledge_ingest_jobs(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
        actor: Dict[str, Any] = Depends(_actor),
    ) -> Dict[str, Any]:
        store = _store()
        trace_id = _trace_id(request)
        log_knowledge_access(store, actor=actor, action="ingest-jobs-list", trace_id=trace_id)
        return {"jobs": store.list_ingest_jobs(limit=limit), "trace_id": trace_id}

    @router.get("/api/knowledge/ingest/jobs/{job_id}")
    async def knowledge_ingest_job(
        job_id: str,
        request: Request,
        actor: Dict[str, Any] = Depends(_actor),
    ) -> Dict[str, Any]:
        store = _store()
        trace_id = _trace_id(request)
        job = store.get_ingest_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Knowledge ingest job not found.")
        log_knowledge_access(store, actor=actor, action="ingest-job-read", trace_id=trace_id)
        return {"job": job, "trace_id": trace_id}

    @router.post("/api/knowledge/ingest/jobs/{job_id}/retry")
    async def knowledge_ingest_job_retry(
        job_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        admin = admin_dependency(request)
        store = _store()
        try:
            job = store.retry_ingest_job(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Knowledge ingest job not found.")
        log_knowledge_access(
            store,
            actor={"username": admin.get("username", "admin"), "auth_type": "cookie"},
            action="ingest-job-retry",
            trace_id=_trace_id(request),
        )
        return {"job": job}

    @router.get("/api/admin/knowledge/candidates")
    async def admin_list_candidates(
        request: Request,
        status: str = Query("pending"),
        limit: int = Query(50, ge=1, le=200),
    ) -> Dict[str, Any]:
        admin_dependency(request)
        store = _store()
        return {"candidates": store.list_candidates(status=status, limit=limit)}

    @router.post("/api/admin/knowledge/candidates/{candidate_id}/approve")
    async def admin_approve_candidate(
        candidate_id: str,
        payload: CandidateDecisionRequest,
        request: Request,
    ) -> Dict[str, Any]:
        admin = admin_dependency(request)
        store = _store()
        try:
            result = store.approve_candidate(
                candidate_id,
                reviewer=admin.get("username", "admin"),
                title=payload.title,
                summary=payload.summary,
                confidence=payload.confidence,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Candidate not found.")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return result

    @router.post("/api/admin/knowledge/candidates/{candidate_id}/reject")
    async def admin_reject_candidate(
        candidate_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        admin = admin_dependency(request)
        store = _store()
        try:
            return store.reject_candidate(candidate_id, reviewer=admin.get("username", "admin"))
        except KeyError:
            raise HTTPException(status_code=404, detail="Candidate not found.")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return router
