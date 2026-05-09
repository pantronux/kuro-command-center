from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import ingestion_registry


def log_retrieval_event(
    dataset_uuid: str,
    chunk_id: Optional[int],
    retrieval_source: str,
    retrieval_score: float,
    hallucination_flag: int = 0,
    username: str = "",
    chat_id: Optional[str] = None,
) -> None:
    ingestion_registry.create_retrieval_event(
        {
            "dataset_uuid": dataset_uuid,
            "chunk_id": chunk_id,
            "retrieval_source": retrieval_source,
            "retrieval_score": retrieval_score,
            "hallucination_flag": hallucination_flag,
            "username": username,
            "chat_id": chat_id,
        }
    )


def get_dataset_analytics(dataset_uuid: Optional[str] = None) -> Dict[str, Any]:
    events = ingestion_registry.list_retrieval_events(limit=500)
    if dataset_uuid:
        events = [event for event in events if event.get("dataset_uuid") == dataset_uuid]
    low_quality = [event for event in events if float(event.get("retrieval_score", 0.0) or 0.0) < 0.4]
    return {
        "events": events,
        "low_quality_events": low_quality,
        "hallucination_count": sum(int(event.get("hallucination_flag") or 0) for event in events),
    }


def get_top_retrieved_datasets(limit: int = 10) -> List[Dict[str, Any]]:
    return ingestion_registry.get_retrieval_summary(limit=limit)
