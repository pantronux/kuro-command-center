from __future__ import annotations

from typing import Any, Dict


def safe_fallback(reason: str) -> Dict[str, Any]:
    return {
        "selected_role": "fallback",
        "reason": reason,
        "status": "degraded",
    }
