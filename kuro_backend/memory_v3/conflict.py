"""Deterministic Memory V3 conflict detection and resolution."""
from __future__ import annotations

from kuro_backend.memory_v3.schemas import MemoryItem
from kuro_backend.memory_v3.store import MemoryV3Store


_OPPOSITE_MARKERS = (
    (" like ", " dislike "),
    (" likes ", " dislikes "),
    (" prefer ", " avoid "),
    (" enabled", " disabled"),
    (" true", " false"),
    (" is ", " is not "),
    (" can ", " cannot "),
)


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


class MemoryConflictResolver:
    def __init__(self, store: MemoryV3Store) -> None:
        self.store = store

    def detect_duplicates(self, candidate: MemoryItem) -> list[MemoryItem]:
        return self.store.find_by_canonical_key(
            canonical_key=candidate.canonical_key,
            workspace_id=candidate.workspace_id,
            username=candidate.username,
            runtime_id=candidate.runtime_id,
            persona_scope=candidate.persona_scope,
            chat_id=candidate.chat_id_nullable,
        )

    def is_exact_duplicate(self, candidate: MemoryItem, existing: MemoryItem) -> bool:
        return (
            candidate.canonical_key == existing.canonical_key
            and _normalize_text(candidate.normalized_summary or candidate.content)
            == _normalize_text(existing.normalized_summary or existing.content)
        )

    def has_basic_contradiction(self, candidate: MemoryItem, existing: MemoryItem) -> bool:
        new_text = f" {_normalize_text(candidate.content)} "
        old_text = f" {_normalize_text(existing.content)} "
        if candidate.canonical_key != existing.canonical_key:
            return False
        if self.is_exact_duplicate(candidate, existing):
            return False
        for left, right in _OPPOSITE_MARKERS:
            if (left in new_text and right in old_text) or (right in new_text and left in old_text):
                return True
        return True

    def mark_conflicts_for_candidate(self, candidate: MemoryItem, existing_items: list[MemoryItem]) -> list[str]:
        conflict_ids: list[str] = []
        for existing in existing_items:
            if existing.memory_id == candidate.memory_id:
                continue
            if not self.has_basic_contradiction(candidate, existing):
                continue
            strategy = (
                "prefer_higher_confidence"
                if candidate.confidence_score != existing.confidence_score
                else "recency_review_required"
            )
            conflict = self.store.create_conflict(
                memory_id_a=existing.memory_id,
                memory_id_b=candidate.memory_id,
                conflict_type="canonical_key_conflict",
                resolution_strategy=strategy,
            )
            conflict_ids.append(conflict.conflict_id)
        return conflict_ids
