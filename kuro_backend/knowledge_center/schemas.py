"""Schemas for the KRC approved knowledge gateway."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


KNOWLEDGE_DOMAINS: tuple[str, ...] = (
    "research",
    "qa",
    "architecture",
    "product",
    "user_preference",
    "paper",
    "methodology",
    "playground",
)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(default="", max_length=1000)
    domains: List[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)


class KnowledgeContextRequest(KnowledgeSearchRequest):
    max_chars: int = Field(default=4000, ge=250, le=12000)


class KnowledgeResult(BaseModel):
    knowledge_id: str
    title: str
    summary: str
    domain: str
    source_type: str
    source_id: str
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    updated_at: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class CandidateKnowledgeRequest(BaseModel):
    source_app: str = Field(..., min_length=1, max_length=80)
    source_chat_id: Optional[str] = Field(default=None, max_length=160)
    domain: str = Field(default="research", max_length=64)
    title: str = Field(default="", max_length=240)
    content: str = Field(..., min_length=1, max_length=32000)
    reason: str = Field(default="", max_length=1000)


class CandidateDecisionRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)
    title: str = Field(default="", max_length=240)
    summary: str = Field(default="", max_length=2000)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)


class KnowledgeIngestRequest(BaseModel):
    source_app: str = Field(..., min_length=1, max_length=80)
    domain: str = Field(default="research.paper", max_length=80)
    source_type: str = Field(default="document", max_length=80)
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="", max_length=64000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeCandidate(BaseModel):
    candidate_id: str
    source_app: str
    source_chat_id: Optional[str] = None
    domain: str
    title: str
    content: str
    reason: str = ""
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: str
    reviewed_at: Optional[str] = None
    reviewer: Optional[str] = None
