from __future__ import annotations

import os

from kuro_backend.cognitive_router.openai_model_adapter import (
    verify_claims_with_openai_model_stub,
)


def test_openai_model_placeholder_schema_is_deterministic(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-placeholder")
    result = verify_claims_with_openai_model_stub(
        ["claim one", "this may be uncertain"],
        contradiction_score=0.10,
    )
    assert result["status"] == "placeholder"
    assert result["mode"] == "stub"
    assert result["adapter"] == "openai_model"
    assert result["network_call"] is False
    assert result["api_key_present"] is True
    assert "claim_verification" in result
    assert isinstance(result["claim_verification"]["verified"], list)
    assert isinstance(result["claim_verification"]["uncertain"], list)
    assert isinstance(result["claim_verification"]["contradictions"], list)


def test_openai_model_placeholder_has_no_network_side_effects(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = dict(os.environ)
    result = verify_claims_with_openai_model_stub(["claim one"], contradiction_score=0.60)
    after = dict(os.environ)
    assert before == after
    assert result["network_call"] is False
    assert result["status"] == "placeholder"
    assert result["claim_verification"]["contradictions"] == ["claim one"]
