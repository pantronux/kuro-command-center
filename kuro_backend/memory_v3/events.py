"""Memory V3 event builders."""
from __future__ import annotations

from kuro_backend.memory_v3.schemas import MemoryEvent, MemoryWriteRequest, stable_hash


def compute_write_idempotency_key(request: MemoryWriteRequest) -> str:
    return stable_hash(
        {
            "workspace_id": request.workspace_id,
            "username": request.username,
            "runtime_id": request.runtime_id,
            "persona_scope": request.persona_scope,
            "chat_id": request.chat_id,
            "source_type": request.source_type,
            "source_id": request.source_id,
            "content": request.content.strip(),
            "memory_type": request.memory_type or "",
        }
    )


def build_write_event(request: MemoryWriteRequest, idempotency_key: str) -> MemoryEvent:
    return MemoryEvent(
        event_type="memory.write.requested",
        idempotency_key=idempotency_key,
        workspace_id=request.workspace_id,
        username=request.username,
        runtime_id=request.runtime_id,
        persona_scope=request.persona_scope,
        chat_id=request.chat_id,
        source_type=request.source_type,
        source_id=request.source_id,
        payload_json={
            "content": request.content,
            "memory_type": request.memory_type,
            "normalized_summary": request.normalized_summary,
            "confidence_score": request.confidence_score,
            "importance_score": request.importance_score,
            "metadata": request.metadata,
        },
        trace_id=request.trace_id,
    )
