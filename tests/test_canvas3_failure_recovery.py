from __future__ import annotations

from kuro_backend.failure_recovery_engine import classify_failure, recovery_payload


def test_failure_recovery_classification() -> None:
    out = classify_failure(RuntimeError("boom"))
    assert out["collapse_detected"] is True
    assert out["recovery_strategy"] in {"retry_lite", "degraded_safe"}


def test_failure_recovery_payload_shape() -> None:
    out = recovery_payload(reason="unit_test")
    assert out["degraded_mode_active"] is True
    assert out["failure_recovery_status"]["collapse_detected"] is True
