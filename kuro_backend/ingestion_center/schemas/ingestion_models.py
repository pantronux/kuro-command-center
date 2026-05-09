from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DatasetRecord:
    dataset_uuid: str
    dataset_name: str
    original_filename: str
    file_path: Optional[str]
    file_hash_sha256: str
    source_type: str
    category: str
    owner_username: str
    ingestion_status: str
    chunk_count: int = 0
    embedding_count: int = 0
    vector_collection: str = ""
    memory_scope: str = ""
    tags_json: str = "[]"
    metadata_json: str = "{}"
    created_at: str = ""
    updated_at: str = ""
    archived_at: Optional[str] = None
    deleted_at: Optional[str] = None
    last_error: Optional[str] = None
    parser_type: Optional[str] = None
    entity_count: int = 0
    summary_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetChunkRecord:
    dataset_uuid: str
    chunk_index: int
    chunk_text: str
    chunk_hash: str
    token_count: int
    embedding_status: str
    retrieval_count: int = 0
    metadata_json: str = "{}"
    created_at: str = ""
    entity_json: str = "[]"
    preview_text: str = ""
    vector_id: Optional[str] = None
    is_orphan: int = 0
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IngestionJobRecord:
    status: str
    dataset_uuid: Optional[str]
    username: str
    job_type: str
    progress_percent: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    logs_json: str = "[]"
    created_at: str = ""
    updated_at: str = ""
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetLineageRecord:
    dataset_uuid: str
    operation_type: str
    created_at: str
    metadata_json: str = "{}"
    parent_dataset_uuid: Optional[str] = None
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetSearchResult:
    dataset_uuid: str
    dataset_name: str
    ingestion_status: str
    original_filename: str
    tags: List[str] = field(default_factory=list)
    matched_chunk_preview: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IngestionDashboardSnapshot:
    totals: Dict[str, Any]
    datasets: List[Dict[str, Any]]
    jobs: List[Dict[str, Any]]
    collection_health: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
