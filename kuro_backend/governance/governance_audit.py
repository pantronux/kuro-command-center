from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


def build_audit_record(username: str, decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "username": username,
        "decision": decision,
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
