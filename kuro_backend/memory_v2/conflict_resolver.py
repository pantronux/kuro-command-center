"""Memory conflict detection and resolution logic."""

# --- Header Doc ---
# Purpose: Detect and resolve conflicting semantic/episodic memories.
# Caller: Memory V2 ingestion pipelines.
# Dependencies: memory_store.py.
# Main Functions: detect_conflicts(), resolve_conflict().
# Side Effects: Marks prior conflicting memories as `conflicted`.

from __future__ import annotations

import logging
from typing import Iterable, List

from kuro_backend.memory_v2.memory_store import KuroMemory, MemoryStore

logger = logging.getLogger(__name__)


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    words_a = set((text_a or "").lower().split())
    words_b = set((text_b or "").lower().split())
    if not words_a and not words_b:
        return 0.0
    union = words_a | words_b
    if not union:
        return 0.0
    return len(words_a & words_b) / len(union)


def detect_conflicts(
    new_memory: KuroMemory,
    existing_memories: Iterable[KuroMemory],
) -> List[KuroMemory]:
    """
    Conflict criteria:
    - Memory type is semantic/episodic on both sides.
    - Same runtime_id, namespace, and username.
    - Jaccard overlap on whitespace tokens > 0.7.
    """
    if new_memory.type not in ("semantic", "episodic"):
        return []
    conflicts: List[KuroMemory] = []
    for mem in existing_memories:
        if mem.type not in ("semantic", "episodic"):
            continue
        if mem.runtime_id != new_memory.runtime_id:
            continue
        if mem.namespace != new_memory.namespace:
            continue
        if (mem.username or "") != (new_memory.username or ""):
            continue
        overlap = _jaccard_similarity(new_memory.content, mem.content)
        if overlap > 0.7:
            conflicts.append(mem)
    return conflicts


def resolve_conflict(
    store: MemoryStore,
    new_memory: KuroMemory,
    conflicting: Iterable[KuroMemory],
) -> None:
    """Newest wins: mark old conflicts. Never raises."""
    for old_mem in conflicting:
        try:
            store.mark_conflicted(old_mem.id)
            logger.info(
                "Conflict resolved old=%r new=%r runtime=%r namespace=%r",
                old_mem.id,
                new_memory.id,
                new_memory.runtime_id,
                new_memory.namespace,
            )
        except Exception as exc:
            logger.error("Failed to mark conflicted memory %r: %s", old_mem.id, exc)
