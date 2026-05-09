from __future__ import annotations

from typing import Any, Dict


def classify_failure(exc: Exception) -> Dict[str, Any]:
    name = type(exc).__name__
    return {
        "error_type": name,
        "collapse_detected": True,
        "recovery_strategy": "retry_lite" if name in {"TimeoutError", "ConnectionError"} else "degraded_safe",
    }


def recovery_payload(*, reason: str) -> Dict[str, Any]:
    return {
        "failure_recovery_status": {
            "collapse_detected": True,
            "recovery_strategy": "degraded_safe",
            "reason": reason,
        },
        "degraded_mode_active": True,
    }
