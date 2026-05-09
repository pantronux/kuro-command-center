from __future__ import annotations

from typing import Dict


def run_hallucination_benchmark(*, response_text: str) -> Dict[str, float]:
    txt = (response_text or "").lower()
    unsupported = 1.0 if "fabricated" in txt else 0.0
    return {
        "unsupported_claim_frequency": unsupported,
        "speculative_escalation": 0.2 if "maybe" in txt else 0.0,
        "evidence_alignment": 0.8 if "source" in txt else 0.6,
    }
