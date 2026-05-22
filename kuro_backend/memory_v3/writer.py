"""Memory V3 write pipeline."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from kuro_backend.memory_v3.conflict import MemoryConflictResolver
from kuro_backend.memory_v3.events import build_write_event, compute_write_idempotency_key
from kuro_backend.memory_v3.policy import MemoryV3Policy
from kuro_backend.memory_v3.provenance import build_provenance, sanitize_provenance
from kuro_backend.memory_v3.schemas import (
    MEMORY_TYPES,
    MemoryItem,
    MemoryWriteRequest,
    MemoryWriteResult,
    stable_hash,
    utc_now_iso,
)
from kuro_backend.memory_v3.store import MemoryV3Store


def _normalize_summary(content: str) -> str:
    return " ".join((content or "").strip().split())[:2000]


def _slug_words(text: str, max_words: int = 8) -> str:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return "_".join(words[:max_words]) or "memory"


class MemoryWriter:
    def __init__(
        self,
        store: Optional[MemoryV3Store] = None,
        policy: Optional[MemoryV3Policy] = None,
    ) -> None:
        self.store = store or MemoryV3Store()
        self.policy = policy or MemoryV3Policy()
        self.conflicts = MemoryConflictResolver(self.store)

    def classify_memory_type(self, request: MemoryWriteRequest) -> str:
        if request.memory_type:
            if request.memory_type not in MEMORY_TYPES:
                raise ValueError(f"unsupported memory_type: {request.memory_type}")
            return request.memory_type
        source_type = (request.source_type or "").lower()
        if source_type in {"uploaded_file", "ingestion"}:
            return "evidence_memory"
        if source_type in {"tool_result", "system_config"}:
            return "operational_memory"
        if source_type in {"market_data_provider", "market"}:
            return "market_signal_memory"
        if "prefer" in request.content.lower() or "likes" in request.content.lower():
            return "user_preference_memory"
        return "semantic_memory"

    def canonical_key_for(self, request: MemoryWriteRequest, memory_type: str, summary: str) -> str:
        if request.canonical_key:
            return request.canonical_key[:256]
        stable_part = stable_hash(
            {
                "workspace_id": request.workspace_id,
                "username": request.username,
                "runtime_id": request.runtime_id,
                "persona_scope": request.persona_scope,
                "memory_type": memory_type,
                "summary": summary.lower(),
            }
        )[:16]
        return f"{memory_type}:{_slug_words(summary)}:{stable_part}"

    def expires_at_for(self, memory_type: str) -> Optional[str]:
        days = self.policy.retention_days_for_type(memory_type)
        if days is None:
            return None
        return (datetime.utcnow() + timedelta(days=int(days))).replace(microsecond=0).isoformat() + "Z"

    def write(self, request: MemoryWriteRequest, *, actor_username: str | None = None) -> MemoryWriteResult:
        scope = request.scope()
        self.policy.validate_scope(scope)
        if not self.policy.can_write(request, actor_username=actor_username):
            raise PermissionError("Memory V3 write denied by policy")

        idempotency_key = compute_write_idempotency_key(request)
        existing_event = self.store.get_event_by_idempotency_key(idempotency_key)
        if existing_event:
            existing_item = self.store.get_memory_item_by_event(existing_event.event_id)
            if existing_item:
                return MemoryWriteResult(
                    event_id=existing_event.event_id,
                    memory_id=existing_item.memory_id,
                    created=False,
                    idempotent=True,
                    status=existing_item.status,
                    canonical_key=existing_item.canonical_key,
                )

        event = self.store.append_event(build_write_event(request, idempotency_key))
        summary = request.normalized_summary or _normalize_summary(request.content)
        memory_type = self.classify_memory_type(request)
        canonical_key = self.canonical_key_for(request, memory_type, summary)
        sensitivity = self.policy.sensitivity_rules(
            request.content,
            explicit=request.sensitivity_level,
        )
        existing_items = self.store.find_by_canonical_key(
            canonical_key=canonical_key,
            workspace_id=request.workspace_id,
            username=request.username,
            runtime_id=request.runtime_id,
            persona_scope=request.persona_scope,
            chat_id=request.chat_id,
        )
        candidate = MemoryItem(
            canonical_key=canonical_key,
            memory_type=memory_type,
            content=request.content,
            normalized_summary=summary,
            confidence_score=request.confidence_score,
            importance_score=request.importance_score,
            sensitivity_level=sensitivity,
            workspace_id=request.workspace_id,
            username=request.username,
            runtime_id=request.runtime_id,
            persona_scope=request.persona_scope,
            chat_id_nullable=request.chat_id,
            expires_at=self.expires_at_for(memory_type),
            source_event_id=event.event_id,
            provenance_json=sanitize_provenance(build_provenance(request, event)),
        )

        for existing in existing_items:
            if self.conflicts.is_exact_duplicate(candidate, existing):
                self.store.log_access(
                    access_type="write",
                    workspace_id=request.workspace_id,
                    username=request.username,
                    runtime_id=request.runtime_id,
                    chat_id=request.chat_id,
                    memory_id=existing.memory_id,
                    trace_id=request.trace_id,
                )
                return MemoryWriteResult(
                    event_id=event.event_id,
                    memory_id=existing.memory_id,
                    created=False,
                    idempotent=False,
                    status=existing.status,
                    canonical_key=existing.canonical_key,
                )

        self.store.upsert_memory_item(candidate)
        conflict_ids = self.conflicts.mark_conflicts_for_candidate(candidate, existing_items)
        stored = self.store.get_memory_item(candidate.memory_id) or candidate
        self.store.log_access(
            access_type="write",
            workspace_id=request.workspace_id,
            username=request.username,
            runtime_id=request.runtime_id,
            chat_id=request.chat_id,
            memory_id=candidate.memory_id,
            trace_id=request.trace_id,
        )
        return MemoryWriteResult(
            event_id=event.event_id,
            memory_id=candidate.memory_id,
            created=True,
            idempotent=False,
            status=stored.status,
            conflict_ids=conflict_ids,
            canonical_key=canonical_key,
        )
