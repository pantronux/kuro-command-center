from __future__ import annotations

from kuro_backend.cognitive_budget_engine import evaluate_budget


def test_cognitive_budget_normal() -> None:
    out = evaluate_budget({"retrieval_retry_count": 1})
    assert out["blocked"] in {True, False}
    assert "limits" in out


def test_cognitive_budget_blocks_excessive_retries() -> None:
    out = evaluate_budget({"retrieval_retry_count": 99})
    assert out["blocked"] is True
    assert "retrieval_expansion_limit_exceeded" in out["budget_enforcement_trace"]
