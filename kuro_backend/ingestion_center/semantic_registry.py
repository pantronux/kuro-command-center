from __future__ import annotations

from typing import Any, Dict, Iterable, List

from . import ingestion_registry


def register_chunks(dataset_uuid: str, chunks: List[Dict[str, Any]], vector_result: Dict[str, Any]) -> Dict[str, Any]:
    vector_ids = vector_result.get("vector_ids") or []
    for chunk in chunks:
        idx = chunk["chunk_index"]
        chunk["vector_id"] = vector_ids[idx] if idx < len(vector_ids) else None
        chunk["embedding_status"] = "completed" if chunk["vector_id"] else "failed"
        chunk["is_orphan"] = 0 if chunk["vector_id"] else 1
    ingestion_registry.replace_chunks(dataset_uuid, chunks)
    return {"chunk_count": len(chunks), "embedding_count": len([c for c in chunks if c.get("vector_id")])}


def mark_orphan_chunks(dataset_uuid: str, vector_ids_missing: Iterable[str]) -> int:
    return ingestion_registry.update_chunk_orphans(dataset_uuid, vector_ids_missing)


def get_dataset_chunks(dataset_uuid: str) -> List[Dict[str, Any]]:
    return ingestion_registry.list_chunks(dataset_uuid)
