"""Policy checks for Memory V3 scopes, types, retention, and access."""
from __future__ import annotations

from typing import Iterable, Optional

from kuro_backend.memory_v3.privacy import classify_sensitivity
from kuro_backend.memory_v3.schemas import MEMORY_TYPES, MemoryReadRequest, MemoryScope, MemoryWriteRequest


class MemoryV3Policy:
    """Deterministic policy layer. No external calls."""

    _RETENTION_DAYS = {
        "ephemeral_context": 1,
        "working_memory": 30,
        "episodic_memory": 365,
        "semantic_memory": None,
        "procedural_memory": None,
        "operational_memory": 180,
        "evidence_memory": 2555,
        "reflective_memory": 365,
        "task_memory": 90,
        "market_signal_memory": 30,
        "user_preference_memory": None,
        "system_policy_memory": None,
    }

    def validate_scope(self, scope: MemoryScope) -> None:
        # Pydantic validates non-empty values; this method centralizes the
        # policy contract for callers that already have a MemoryScope.
        for field_name in (
            "workspace_id",
            "username",
            "runtime_id",
            "persona_scope",
            "chat_id",
            "source_type",
            "source_id",
        ):
            if not str(getattr(scope, field_name, "") or "").strip():
                raise ValueError(f"{field_name} is required for Memory V3 scope")

    def allowed_memory_types_for_runtime(self, runtime_id: str) -> Iterable[str]:
        runtime = (runtime_id or "sovereign").strip()
        if runtime == "market":
            return tuple(MEMORY_TYPES)
        return tuple(MEMORY_TYPES)

    def retention_days_for_type(self, memory_type: str) -> Optional[int]:
        return self._RETENTION_DAYS.get(memory_type, 365)

    def sensitivity_rules(self, content: str, explicit: str | None = None) -> str:
        return classify_sensitivity(content, explicit=explicit)

    def can_read(self, request: MemoryReadRequest, actor_username: str | None = None) -> bool:
        actor = (actor_username or request.username or "").strip()
        return bool(actor and actor == request.username)

    def can_write(self, request: MemoryWriteRequest, actor_username: str | None = None) -> bool:
        actor = (actor_username or request.username or "").strip()
        return bool(actor and actor == request.username)

    def can_redact(self, *, actor_username: str, target_username: str, admin: bool = False) -> bool:
        if admin:
            return True
        return bool(actor_username and actor_username == target_username)
