"""Basic Memory V3 read path for core tests and admin diagnostics."""
from __future__ import annotations

from typing import Optional

from kuro_backend.memory_v3.policy import MemoryV3Policy
from kuro_backend.memory_v3.schemas import MemoryReadRequest, MemoryReadResult, stable_hash
from kuro_backend.memory_v3.store import MemoryV3Store


class MemoryV3Reader:
    def __init__(
        self,
        store: Optional[MemoryV3Store] = None,
        policy: Optional[MemoryV3Policy] = None,
    ) -> None:
        self.store = store or MemoryV3Store()
        self.policy = policy or MemoryV3Policy()

    def read(self, request: MemoryReadRequest, *, actor_username: str | None = None) -> MemoryReadResult:
        if not self.policy.can_read(request, actor_username=actor_username):
            raise PermissionError("Memory V3 read denied by policy")
        query_hash = stable_hash(
            {
                "workspace_id": request.workspace_id,
                "username": request.username,
                "runtime_id": request.runtime_id,
                "persona_scope": request.persona_scope,
                "chat_id": request.chat_id or "",
                "query": request.query,
                "memory_type": request.memory_type or "",
            }
        )
        items = self.store.search_memory_items_basic(
            workspace_id=request.workspace_id,
            username=request.username,
            runtime_id=request.runtime_id,
            persona_scope=request.persona_scope,
            query_text=request.query,
            memory_type=request.memory_type,
            chat_id=request.chat_id,
            include_cross_chat=request.include_cross_chat,
            limit=request.limit,
        )
        self.store.log_access(
            access_type="read",
            workspace_id=request.workspace_id,
            username=request.username,
            runtime_id=request.runtime_id,
            chat_id=request.chat_id,
            query_hash=query_hash,
            trace_id=request.trace_id,
        )
        return MemoryReadResult(items=items, query_hash=query_hash, access_logged=True)
