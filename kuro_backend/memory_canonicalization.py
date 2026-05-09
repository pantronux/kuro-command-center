from __future__ import annotations

from typing import Any, Dict, Iterable, List


def canonicalize_memory_payload(*, user_input: str, final_response: str) -> Dict[str, Any]:
    clean_response = " ".join(str(final_response or "").split())
    canonical_summary = clean_response[:400]
    contradiction_detected = False
    if user_input and final_response:
        contradiction_detected = "not" in user_input.lower() and "yes" in final_response.lower()
    temporal_score = 0.9
    return {
        "validation_passed": bool(canonical_summary),
        "canonical_summary": canonical_summary,
        "conflict_resolution": "none" if not contradiction_detected else "soft_downgrade",
        "temporal_score": temporal_score,
        "promoted": bool(canonical_summary),
        "contradiction_detected": contradiction_detected,
    }


def canonical_selection_score(memories: Iterable[Any]) -> float:
    rows = list(memories or [])
    if not rows:
        return 0.0
    score = min(1.0, 0.4 + (len(rows) * 0.08))
    return max(0.0, score)
