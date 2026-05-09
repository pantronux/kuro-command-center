from __future__ import annotations

from kuro_backend.source_reliability_engine import score_sources


def test_source_reliability_empty() -> None:
    out = score_sources([])
    assert out["credibility_score"] == 0.0


def test_source_reliability_mixed_sources() -> None:
    out = score_sources(
        [
            {"source_type": "scholar", "cited_by": 12, "title": "Paper"},
            {"source_type": "news", "date": "2026-05-09", "title": "News"},
        ]
    )
    assert 0.0 <= out["retrieval_trustworthiness"] <= 1.0
