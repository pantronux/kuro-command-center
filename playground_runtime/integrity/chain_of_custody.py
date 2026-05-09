"""Chain-of-custody event builders."""

from __future__ import annotations

from typing import Optional


def build_custody_event(
    *,
    artifact_id: str,
    action_type: str,
    actor: Optional[str],
    previous_hash: Optional[str] = None,
    new_hash: Optional[str] = None,
    notes: str = "",
) -> dict:
    return {
        "artifact_id": artifact_id,
        "action_type": action_type,
        "actor": actor or "system",
        "previous_hash": previous_hash,
        "new_hash": new_hash,
        "notes": notes,
    }
