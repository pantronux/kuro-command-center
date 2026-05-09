from __future__ import annotations

from typing import Any, Dict

from .grounding_score import compute_grounding_score
from .governance_compliance_test import compute_governance_compliance
from .hallucination_benchmark import run_hallucination_benchmark
from .memory_integrity_benchmark import compute_memory_integrity
from .multi_model_alignment import compute_multi_model_alignment
from .persona_consistency import compute_persona_consistency


def run_regression_snapshot(state: Dict[str, Any], response_text: str) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    snapshot.update(run_hallucination_benchmark(response_text=response_text))
    snapshot.update(compute_grounding_score(state))
    snapshot.update(compute_persona_consistency(persona_mode=str(state.get("persona_mode", "")), response_text=response_text))
    snapshot.update(compute_memory_integrity(contradiction_score=float(state.get("contradiction_score", 0.0) or 0.0)))
    snapshot.update(compute_multi_model_alignment(state.get("consensus_result") or {}))
    snapshot.update(compute_governance_compliance(state.get("governance_status") or {}))
    return snapshot
