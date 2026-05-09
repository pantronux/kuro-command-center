from __future__ import annotations

from typing import Dict


def retention_policy_snapshot() -> Dict[str, int | str]:
    return {
        "retention_days": 30,
        "deletion_rights": "supported",
        "auditability": "enabled",
    }
