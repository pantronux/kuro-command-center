from __future__ import annotations

from kuro_backend.intelligence.response_sanitizer import response_sanitizer
from kuro_backend.intelligence.stream_safety import sanitize_stream_chunk
from kuro_backend.intelligence.retrieval_quality import score_retrieval_quality
from kuro_backend import personas


def test_response_sanitizer_strips_internal_labels() -> None:
    raw = "[VERIFIED: memory] Halo. [SPECULATIVE] Ini uji. [UNKNOWN]"
    clean = response_sanitizer.sanitize_user_output(raw)
    assert "[VERIFIED" not in clean
    assert "[SPECULATIVE]" not in clean
    assert "[UNKNOWN]" not in clean


def test_stream_safety_blocks_internal_policy_markers() -> None:
    raw = "MANDATORY CLAIM LABELING GRAMMAR\n[INFERRED] hidden"
    assert sanitize_stream_chunk(raw) == ""


def test_retrieval_quality_returns_valid_grade() -> None:
    report = score_retrieval_quality(
        "cek status backup terbaru",
        [
            "backup nightly 2026-05-08 success",
            "latest backup completed with status success",
        ],
    )
    assert report.retrieval_grade in {"grounded", "partial", "weak", "contradictory", "stale", "irrelevant"}


def test_autorag_notification_supports_six_state() -> None:
    assert personas.build_autorag_notification_block("grounded", 0) == ""
    txt = personas.build_autorag_notification_block("weak", 1)
    assert "RETRIEVAL QUALITY: WEAK" in txt
