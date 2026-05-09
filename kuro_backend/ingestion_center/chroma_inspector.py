from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import ingestion_registry
from .embedding_manager import _get_client


def get_collection_health() -> Dict[str, Any]:
    try:
        client = _get_client()
        collections = []
        for collection_ref in client.list_collections():
            collection = collection_ref
            if not hasattr(collection_ref, "get"):
                collection = client.get_or_create_collection(name=str(collection_ref))
            data = collection.get()
            collections.append(
                {
                    "name": collection.name,
                    "vector_count": len(data.get("ids", [])),
                }
            )
        return {"status": "success", "backend": "chroma", "collections": collections, "orphan_chunks": find_orphan_chunks()}
    except Exception as exc:
        return {"status": "degraded", "backend": "chroma", "collections": [], "orphan_chunks": find_orphan_chunks(), "error": str(exc)}


def get_dataset_vector_health(dataset_uuid: str) -> Dict[str, Any]:
    dataset = ingestion_registry.get_dataset(dataset_uuid) or {}
    chunks = ingestion_registry.list_chunks(dataset_uuid)
    vector_count = len([chunk for chunk in chunks if chunk.get("vector_id")])
    orphan_chunks = [chunk for chunk in chunks if int(chunk.get("is_orphan") or 0) == 1]
    return {
        "dataset_uuid": dataset_uuid,
        "dataset_name": dataset.get("dataset_name", ""),
        "registered_chunks": len(chunks),
        "vector_count": vector_count,
        "orphan_count": len(orphan_chunks),
        "collection_name": dataset.get("vector_collection", ""),
        "status": "healthy" if vector_count == len(chunks) else "degraded",
    }


def find_orphan_chunks(dataset_uuid: Optional[str] = None) -> List[Dict[str, Any]]:
    if dataset_uuid:
        rows = ingestion_registry.list_chunks(dataset_uuid)
    else:
        rows = ingestion_registry.fetch_all("SELECT * FROM dataset_chunks WHERE is_orphan = 1 ORDER BY created_at DESC")
    return [row for row in rows if int(row.get("is_orphan") or 0) == 1]
