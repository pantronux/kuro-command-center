"""FastAPI routes for Kuro Research Center artifacts."""
from __future__ import annotations

from typing import Callable, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from kuro_backend.knowledge_center.candidates import KnowledgeStore
from kuro_backend.knowledge_center.schemas import KnowledgeIngestRequest
from kuro_backend.research_center.db import ResearchStore
from kuro_backend.research_center.schemas import (
    ArgumentEdgeCreate,
    ArgumentNodeCreate,
    NoveltyGapCreate,
    PaperSourceCreate,
    ResearchClaimCreate,
    ResearchIngestRequest,
    ResearchProjectCreate,
    ResearchProjectUpdate,
    ResearchQuestionCreate,
)
from kuro_backend.research_center.service import ResearchService


def _payload(model: object) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()  # type: ignore[no-any-return]
    return model.dict()  # type: ignore[attr-defined,no-any-return]


def create_research_router(
    *,
    auth_dependency: Callable[[Request], Dict[str, str]],
) -> APIRouter:
    router = APIRouter()

    def _store() -> ResearchStore:
        return ResearchStore()

    def _owner(user: Dict[str, str] = Depends(auth_dependency)) -> str:
        return user.get("username", "unknown")

    @router.get("/api/research/projects")
    async def list_projects(owner: str = Depends(_owner)) -> Dict[str, object]:
        return {"projects": _store().list_projects(owner=owner)}

    @router.post("/api/research/projects")
    async def create_project(
        payload: ResearchProjectCreate,
        owner: str = Depends(_owner),
    ) -> Dict[str, object]:
        project = _store().create_project(
            owner=owner,
            title=payload.title,
            description=payload.description,
            status=payload.status,
        )
        return {"project": project}

    @router.get("/api/research/projects/{project_id}")
    async def get_project(project_id: str, owner: str = Depends(_owner)) -> Dict[str, object]:
        project = _store().get_project(owner=owner, project_id=project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Research project not found.")
        return {"project": project}

    @router.patch("/api/research/projects/{project_id}")
    async def update_project(
        project_id: str,
        payload: ResearchProjectUpdate,
        owner: str = Depends(_owner),
    ) -> Dict[str, object]:
        project = _store().update_project(
            owner=owner,
            project_id=project_id,
            updates=payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True),
        )
        if not project:
            raise HTTPException(status_code=404, detail="Research project not found.")
        return {"project": project}

    @router.post("/api/research/sources")
    async def create_source(
        payload: PaperSourceCreate,
        owner: str = Depends(_owner),
    ) -> Dict[str, object]:
        try:
            source = _store().create_source(owner=owner, payload=_payload(payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="Research project not found.")
        return {"source": source}

    @router.get("/api/research/sources")
    async def list_sources(
        project_id: str | None = Query(default=None),
        owner: str = Depends(_owner),
    ) -> Dict[str, object]:
        return {"sources": _store().list_sources(owner=owner, project_id=project_id)}

    @router.get("/api/research/sources/{source_id}")
    async def get_source(source_id: str, owner: str = Depends(_owner)) -> Dict[str, object]:
        source = _store().get_source(owner=owner, source_id=source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Research source not found.")
        return {"source": source}

    @router.post("/api/research/claims")
    async def create_claim(payload: ResearchClaimCreate, owner: str = Depends(_owner)) -> Dict[str, object]:
        try:
            claim = _store().create_claim(owner=owner, payload=_payload(payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="Research project not found.")
        return {"claim": claim}

    @router.get("/api/research/claims")
    async def list_claims(
        project_id: str | None = Query(default=None),
        owner: str = Depends(_owner),
    ) -> Dict[str, object]:
        return {"claims": _store().list_claims(owner=owner, project_id=project_id)}

    @router.post("/api/research/questions")
    async def create_question(payload: ResearchQuestionCreate, owner: str = Depends(_owner)) -> Dict[str, object]:
        try:
            question = _store().create_question(owner=owner, payload=_payload(payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="Research project not found.")
        return {"question": question}

    @router.get("/api/research/questions")
    async def list_questions(
        project_id: str | None = Query(default=None),
        owner: str = Depends(_owner),
    ) -> Dict[str, object]:
        return {"questions": _store().list_questions(owner=owner, project_id=project_id)}

    @router.post("/api/research/novelty-gaps")
    async def create_gap(payload: NoveltyGapCreate, owner: str = Depends(_owner)) -> Dict[str, object]:
        try:
            gap = _store().create_gap(owner=owner, payload=_payload(payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="Research project not found.")
        return {"gap": gap}

    @router.get("/api/research/novelty-gaps")
    async def list_gaps(
        project_id: str | None = Query(default=None),
        owner: str = Depends(_owner),
    ) -> Dict[str, object]:
        return {"gaps": _store().list_gaps(owner=owner, project_id=project_id)}

    @router.post("/api/research/argument-map/nodes")
    async def create_argument_node(payload: ArgumentNodeCreate, owner: str = Depends(_owner)) -> Dict[str, object]:
        try:
            node = _store().create_argument_node(owner=owner, payload=_payload(payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="Research project not found.")
        return {"node": node}

    @router.post("/api/research/argument-map/edges")
    async def create_argument_edge(payload: ArgumentEdgeCreate, owner: str = Depends(_owner)) -> Dict[str, object]:
        try:
            edge = _store().create_argument_edge(owner=owner, payload=_payload(payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="Research project not found.")
        return {"edge": edge}

    @router.get("/api/research/argument-map")
    async def get_argument_map(project_id: str = Query(...), owner: str = Depends(_owner)) -> Dict[str, object]:
        if not _store().get_project(owner=owner, project_id=project_id):
            raise HTTPException(status_code=404, detail="Research project not found.")
        return _store().argument_map(owner=owner, project_id=project_id)

    @router.post("/api/research/ingest")
    async def research_ingest(payload: ResearchIngestRequest, owner: str = Depends(_owner)) -> Dict[str, object]:
        service = ResearchService(_store())
        try:
            source = service.create_research_ingest_source(
                owner=owner,
                project_id=payload.project_id,
                title=payload.title,
                source_type=payload.source_type,
                metadata=payload.metadata,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Research project not found.")

        knowledge_job = KnowledgeStore().create_ingest_job(
            KnowledgeIngestRequest(
                source_app="krc",
                domain="research.paper",
                source_type=payload.source_type,
                title=payload.title,
                content=payload.content,
                metadata={
                    **payload.metadata,
                    "research_project_id": payload.project_id,
                    "research_source_id": source["source_id"],
                },
            )
        )
        return {"source": source, "knowledge_ingest_job": knowledge_job}

    return router
