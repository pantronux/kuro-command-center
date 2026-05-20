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
    raw_events = ingestion_registry.list_retrieval_events(limit=500)

    events = []
    low_quality = []
    hallucination_count = 0

    # ⚡ Bolt Optimization: Replaced multiple list comprehensions and sum() generator
    # expressions with a single explicit for-loop to prevent redundant O(n) traversals
    # and avoid intermediate object allocations (~3x fewer traversals).
    for event in raw_events:
        if dataset_uuid and event.get("dataset_uuid") != dataset_uuid:
            continue

        events.append(event)

        if float(event.get("retrieval_score", 0.0) or 0.0) < 0.4:
            low_quality.append(event)

        hallucination_count += int(event.get("hallucination_flag") or 0)

    return {
        "events": events,
        "low_quality_events": low_quality,
        "hallucination_count": hallucination_count,
    }


def get_top_retrieved_datasets(limit: int = 10) -> List[Dict[str, Any]]:
    return ingestion_registry.get_retrieval_summary(limit=limit)
