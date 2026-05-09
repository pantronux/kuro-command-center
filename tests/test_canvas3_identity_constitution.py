from __future__ import annotations

from kuro_backend.constitution_engine import check_constitution
from kuro_backend.identity_core import evaluate_identity_alignment


def test_identity_core_alignment_shape() -> None:
    out = evaluate_identity_alignment("jawaban ter-grounding dan hati-hati")
    assert "identity_score" in out
    assert "anchors" in out


def test_constitution_detects_violation() -> None:
    out = check_constitution(response_text="This is 100% guaranteed.")
    assert out["passed"] is False
    assert len(out["violations"]) >= 1
