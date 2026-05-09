from __future__ import annotations

from typing import Dict


def build_tenant_context(username: str) -> Dict[str, str]:
    return {
        "tenant_id": f"tenant:{username}",
        "workspace_scope": username,
        "isolation_mode": "strict_user_scope",
    }
