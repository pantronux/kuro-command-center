from __future__ import annotations

from typing import Any, Dict


def compute_multi_model_alignment(consensus_result: Dict[str, Any]) -> Dict[str, float]:
    cscore = float((consensus_result or {}).get("consensus_score", 0.0) or 0.0)
    return {"multi_model_alignment": cscore}
