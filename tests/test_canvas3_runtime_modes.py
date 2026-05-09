from __future__ import annotations

from kuro_backend.runtime_modes import resolve_runtime_mode


def test_runtime_mode_balanced_default() -> None:
    out = resolve_runtime_mode("BALANCED")
    assert out["runtime_mode"] == "BALANCED"
    assert "profile" in out


def test_runtime_mode_fallback_to_balanced() -> None:
    out = resolve_runtime_mode("UNKNOWN_MODE")
    assert out["runtime_mode"] == "BALANCED"
