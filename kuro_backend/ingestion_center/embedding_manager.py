from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

from kuro_backend.config import settings

logger = logging.getLogger(__name__)
logger.propagate = False

try:
    import chromadb
except Exception:  # pragma: no cover
    chromadb = None

CHROMA_DIR = os.path.join(settings.WORKING_DIR, "kuro_chromadb", "ingestion_center")


def _stable_embedding(text: str, dims: int = 16) -> List[float]:
    digest = hashlib.sha256((text or "").encode("utf-8", errors="replace")).digest()
    values: List[float] = []
    while len(values) < dims:
        for byte in digest:
            values.append((byte / 255.0) * 2 - 1)
            if len(values) >= dims:
                break
    return values


def _get_client():
    if chromadb is None:
        raise RuntimeError("chromadb not available")
    os.makedirs(CHROMA_DIR, exist_ok=True)
    return chromadb.PersistentClient(path=CHROMA_DIR)


def _get_collection_name(owner_username: str) -> str:
    return f"kuro_ingestion_{owner_username}".lower()


def embed_chunks(dataset_uuid: str, chunks: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
    owner_username = metadata.get("owner_username", "unknown")
    collection_name = _get_collection_name(owner_username)
    try:
        client = _get_client()
        collection = client.get_or_create_collection(name=collection_name)
        ids = [f"{dataset_uuid}:{chunk['chunk_index']}" for chunk in chunks]
        documents = [chunk["chunk_text"] for chunk in chunks]
        metadatas = [
            {
                "dataset_uuid": dataset_uuid,
                "chunk_index": chunk["chunk_index"],
                "dataset_name": metadata.get("dataset_name", ""),
                "source_type": metadata.get("source_type", ""),
            }
            for chunk in chunks
        ]
        embeddings = [_stable_embedding(chunk["chunk_text"]) for chunk in chunks]
        if ids:
            try:
                collection.delete(ids=ids)
            except Exception:
                pass
            collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        return {
            "status": "completed",
            "collection_name": collection_name,
            "vector_ids": ids,
            "embedding_count": len(ids),
            "memory_scope": "chroma_only",
        }
    except Exception as exc:
        logger.warning("[INGESTION] vector write failed for %s: %s", dataset_uuid, exc)
        return {
            "status": "failed",
            "collection_name": collection_name,
            "vector_ids": [],
            "embedding_count": 0,
            "memory_scope": "chroma_only",
            "error": str(exc),
        }


def delete_vectors(dataset_uuid: str, owner_username: Optional[str] = None) -> Dict[str, Any]:
    collection_name = _get_collection_name(owner_username or "unknown")
    try:
        client = _get_client()
        collection = client.get_or_create_collection(name=collection_name)
        prefix = f"{dataset_uuid}:"
        try:
            found = collection.get(where={"dataset_uuid": dataset_uuid})
            ids = found.get("ids", []) if isinstance(found, dict) else []
        except Exception:
            ids = []
        if not ids:
            maybe = collection.get()
            ids = [item for item in maybe.get("ids", []) if str(item).startswith(prefix)]
        if ids:
            collection.delete(ids=ids)
        return {"status": "success", "deleted_count": len(ids), "collection_name": collection_name}
    except Exception as exc:
        return {"status": "failed", "deleted_count": 0, "collection_name": collection_name, "error": str(exc)}


def rebuild_vectors(dataset_uuid: str, chunks: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
    delete_vectors(dataset_uuid, metadata.get("owner_username"))
    return embed_chunks(dataset_uuid, chunks, metadata)
