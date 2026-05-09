from __future__ import annotations

from typing import Dict


def compute_memory_integrity(*, contradiction_score: float) -> Dict[str, float]:
    score = max(0.0, min(1.0, 1.0 - float(contradiction_score)))
    return {"memory_integrity": score}
