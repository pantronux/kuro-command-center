from __future__ import annotations

from kuro_backend.memory_canonicalization import canonical_selection_score, canonicalize_memory_payload


def test_memory_canonicalization_payload_shape() -> None:
    out = canonicalize_memory_payload(
        user_input="tolong simpulkan agenda minggu ini",
        final_response="Agenda minggu ini berfokus pada validasi data dan persiapan laporan.",
    )
    assert out["validation_passed"] is True
    assert isinstance(out["canonical_summary"], str)
    assert "temporal_score" in out


def test_memory_canonical_selection_score() -> None:
    score = canonical_selection_score([{"memory": "a"}, {"memory": "b"}])
    assert 0.0 <= score <= 1.0
