"""Retention and redaction engine for Memory V3."""
from __future__ import annotations

from typing import Optional

from kuro_backend.memory_v3.policy import MemoryV3Policy
from kuro_backend.memory_v3.store import MemoryV3Store


class MemoryRetentionEngine:
    def __init__(
        self,
        store: Optional[MemoryV3Store] = None,
        policy: Optional[MemoryV3Policy] = None,
    ) -> None:
        self.store = store or MemoryV3Store()
        self.policy = policy or MemoryV3Policy()

    def expire_stale_memories(self) -> int:
        return self.store.mark_expired()

    def mark_low_confidence_temporary_for_review(self, threshold: float = 0.3) -> int:
        self.store.init_db()
        with self.store.connection_manager.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE memory_items
                SET status = 'deprecated', updated_at = datetime('now')
                WHERE status = 'active'
                  AND memory_type IN ('ephemeral_context', 'working_memory')
                  AND confidence_score < ?
                """,
                (float(threshold),),
            )
            return int(cur.rowcount or 0)

    def redact_sensitive_item(
        self,
        memory_id: str,
        *,
        actor_username: str,
        target_username: str,
        reason: str,
        admin: bool = False,
    ) -> bool:
        if not self.policy.can_redact(
            actor_username=actor_username,
            target_username=target_username,
            admin=admin,
        ):
            raise PermissionError("Memory V3 redaction denied by policy")
        return self.store.redact_memory(
            memory_id,
            actor_username=actor_username,
            reason=reason,
        )
