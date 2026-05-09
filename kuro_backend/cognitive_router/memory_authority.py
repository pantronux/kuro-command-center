from __future__ import annotations

from typing import Any, Dict


def canonicalize_memory_write(*, user_input: str, consensus_result: Dict[str, Any], source_models: list[str] | None = None) -> Dict[str, Any]:
    src = source_models or ["gemini"]
    return {
        "domain": "sovereign_cognition_runtime",
        "confidence": float(consensus_result.get("consensus_score", 0.0)),
        "source_models": src,
        "canonical_summary": (user_input or "").strip()[:240],
    }
