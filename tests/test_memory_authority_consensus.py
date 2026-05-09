from __future__ import annotations

from kuro_backend.cognitive_router.consensus_engine import run_consensus
from kuro_backend.cognitive_router.memory_authority import canonicalize_memory_write


def test_consensus_engine_produces_valid_label() -> None:
    result = run_consensus(
        confidence_score=0.88,
        contradiction_score=0.12,
        router_decision={"selected_role": "gemini_primary"},
    )
    assert 0.0 <= float(result["consensus_score"]) <= 1.0
    assert result["consensus_label"] in {"stable", "fragile", "conflicted"}
    assert result["selected_role"] == "gemini_primary"


def test_memory_authority_canonicalization_uses_consensus_score() -> None:
    consensus = run_consensus(
        confidence_score=0.72,
        contradiction_score=0.20,
        router_decision={"selected_role": "openai_model_placeholder"},
    )
    canonical = canonicalize_memory_write(
        user_input="Susun ringkasan keputusan arsitektur runtime",
        consensus_result=consensus,
        source_models=["gemini", "openai_model_placeholder"],
    )
    assert canonical["domain"] == "sovereign_cognition_runtime"
    assert canonical["confidence"] == consensus["consensus_score"]
    assert canonical["source_models"] == ["gemini", "openai_model_placeholder"]
    assert isinstance(canonical["canonical_summary"], str)
    assert canonical["canonical_summary"]
