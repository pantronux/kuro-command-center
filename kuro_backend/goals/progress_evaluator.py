from __future__ import annotations

from typing import Any, Dict


def evaluate_progress(execution_state: Dict[str, Any]) -> Dict[str, Any]:
    ratio = float(execution_state.get("completion_ratio", 0.0) or 0.0)
    stalled = int(execution_state.get("stalled", 0) or 0)
    drift = max(0.0, min(1.0, (stalled * 0.2) + (0.4 - ratio if ratio < 0.4 else 0.0)))
    return {
        "completion_ratio": ratio,
        "strategic_drift": drift,
        "reprioritization_needed": drift >= 0.45,
    }
