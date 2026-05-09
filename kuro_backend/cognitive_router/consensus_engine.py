from __future__ import annotations

from typing import Any, Dict


def run_consensus(*, confidence_score: float, contradiction_score: float, router_decision: Dict[str, Any]) -> Dict[str, Any]:
    consensus_score = max(0.0, min(1.0, confidence_score - contradiction_score * 0.4))
    return {
        "consensus_score": consensus_score,
        "consensus_label": "stable" if consensus_score >= 0.7 else "fragile" if consensus_score >= 0.45 else "conflicted",
        "selected_role": router_decision.get("selected_role", "gemini_primary"),
    }
