from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RetrievalEventRecord:
    dataset_uuid: str
    chunk_id: Optional[int]
    retrieval_source: str
    retrieval_score: float
    hallucination_flag: int
    created_at: str
    username: str = ""
    chat_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalOverview:
    top_datasets: List[Dict[str, Any]] = field(default_factory=list)
    low_quality_events: List[Dict[str, Any]] = field(default_factory=list)
    hallucination_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CollectionHealth:
    status: str
    collections: List[Dict[str, Any]] = field(default_factory=list)
    orphan_chunks: List[Dict[str, Any]] = field(default_factory=list)
    backend: str = "chroma"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticGraphPayload:
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
