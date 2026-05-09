from __future__ import annotations

from kuro_backend.evaluation_runtime.regression_suite import run_regression_snapshot


def test_evaluation_runtime_snapshot_shape() -> None:
    state = {
        "confidence_score": 0.8,
        "contradiction_score": 0.1,
        "persona_mode": "consultant",
        "consensus_result": {"consensus_score": 0.75},
        "governance_status": {"action": "allow"},
    }
    snap = run_regression_snapshot(state, "response with source mention")
    assert "grounding_score" in snap
    assert "persona_consistency" in snap
    assert "multi_model_alignment" in snap
