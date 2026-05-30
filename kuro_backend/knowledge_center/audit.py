"""Audit logging helpers for the KRC knowledge gateway."""
from __future__ import annotations

from typing import Any, Dict


def log_knowledge_access(store: Any, *, actor: Dict[str, Any], action: str, trace_id: str = "") -> None:
    try:
        store.log_audit(
            actor=str(actor.get("username") or "unknown"),
            auth_type=str(actor.get("auth_type") or "unknown"),
            action=action,
            trace_id=trace_id,
        )
    except Exception:
        # Audit must not turn approved knowledge reads into outages.
        return
