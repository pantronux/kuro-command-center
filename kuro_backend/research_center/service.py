"""Service helpers for KRC research workflows."""
from __future__ import annotations

from typing import Any, Dict

from kuro_backend.research_center.db import ResearchStore


class ResearchService:
    def __init__(self, store: ResearchStore | None = None) -> None:
        self.store = store or ResearchStore()

    def create_research_ingest_source(
        self,
        *,
        owner: str,
        project_id: str,
        title: str,
        source_type: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.store.create_source(
            owner=owner,
            payload={
                "project_id": project_id,
                "title": title,
                "authors": metadata.get("authors") or [],
                "year": metadata.get("year"),
                "venue": metadata.get("venue") or "",
                "doi": metadata.get("doi") or "",
                "url": metadata.get("url") or "",
                "file_ref": metadata.get("file_ref") or "",
                "status": "queued",
                "provenance": {"workflow": "krc_research_ingest", "source_type": source_type},
            },
        )
