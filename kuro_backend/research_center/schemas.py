"""Pydantic schemas for KRC PhD research artifacts."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ResearchProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    status: str = Field(default="active", max_length=40)


class ResearchProjectUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=240)
    description: Optional[str] = Field(default=None, max_length=4000)
    status: Optional[str] = Field(default=None, max_length=40)


class PaperSourceCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=500)
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = Field(default=None, ge=1800, le=2200)
    venue: str = Field(default="", max_length=240)
    doi: str = Field(default="", max_length=160)
    url: str = Field(default="", max_length=1000)
    file_ref: str = Field(default="", max_length=1000)
    status: str = Field(default="candidate", max_length=40)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class ResearchClaimCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    source_id: str = Field(default="", max_length=80)
    claim_text: str = Field(..., min_length=1, max_length=8000)
    claim_type: str = Field(default="finding", max_length=80)
    evidence_quote: str = Field(default="", max_length=8000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    page_or_section: str = Field(default="", max_length=160)


class ResearchQuestionCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    question: str = Field(..., min_length=1, max_length=4000)
    status: str = Field(default="open", max_length=40)
    rationale: str = Field(default="", max_length=4000)


class NoveltyGapCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1, max_length=8000)
    related_sources: List[str] = Field(default_factory=list)
    strength: str = Field(default="medium", max_length=40)
    risk: str = Field(default="", max_length=2000)
    status: str = Field(default="open", max_length=40)


class ArgumentNodeCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    node_type: str = Field(default="claim", max_length=80)
    label: str = Field(..., min_length=1, max_length=240)
    content: str = Field(default="", max_length=8000)
    source_id: str = Field(default="", max_length=80)


class ArgumentEdgeCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    from_node_id: str = Field(..., min_length=1, max_length=80)
    to_node_id: str = Field(..., min_length=1, max_length=80)
    relation: str = Field(default="supports", max_length=80)


class ResearchIngestRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="", max_length=64000)
    source_type: str = Field(default="paper", max_length=80)
    metadata: Dict[str, Any] = Field(default_factory=dict)
