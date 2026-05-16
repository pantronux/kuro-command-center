from __future__ import annotations

from datetime import datetime, timezone

from playground_runtime.divergence.semantic_diff import compute_semantic_divergence
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def _trace(trace_id: str, provider_id: str, text: str, grounding_count: int, citations: int, total_tokens: int) -> CanonicalInferenceTrace:
    return CanonicalInferenceTrace(
        trace_id=trace_id,
        session_id="s1",
        execution_id=f"e-{trace_id}",
        provider_id=provider_id,
        model_id="m",
        model_version="v",
        schema_version="x/1.0",
        prompt_sha256="prompt",
        dataset_version=None,
        collected_at_utc=datetime.now(timezone.utc),
        response_text=text,
        finish_reason="stop",
        input_tokens=1,
        output_tokens=1,
        total_tokens=total_tokens,
        latency_ms=1.0,
        grounding_chunks=[{"g": i} for i in range(grounding_count)],
        citation_objects=[{"c": i} for i in range(citations)],
        safety_ratings=None,
        provider_raw_id="r",
        forensic_flags=[],
        normalization_warnings=[],
        extra_fields={},
    )


def test_compute_semantic_divergence_returns_expected_fields():
    rows = compute_semantic_divergence(
        [
            _trace("t1", "openai", "alpha beta gamma", 0, 0, 10),
            _trace("t2", "gemini", "alpha delta epsilon", 2, 2, 15),
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert "semantic_overlap" in row
    assert "claim_overlap" in row
    assert "grounding_delta" in row
    assert "provider_variance" in row
    assert "classification_label_left" in row
    assert "classification_label_right" in row
    assert "classification_agreement" in row
    assert "contradiction_detected" in row


def test_semantic_divergence_agreement_no_false_contradiction():
    rows = compute_semantic_divergence(
        [
            _trace(
                "t1",
                "gemini",
                "This prompt is classified as malicious because it attempts prompt injection.",
                0,
                0,
                120,
            ),
            _trace(
                "t2",
                "ollama",
                "Final classification: Malicious. It tries to ignore previous instructions.",
                0,
                0,
                140,
            ),
        ]
    )
    row = rows[0]
    assert row["classification_label_left"] == "malicious"
    assert row["classification_label_right"] == "malicious"
    assert row["classification_agreement"] is True
    assert row["contradiction_detected"] is False
    assert "LOW_OVERLAP_CONTRADICTION_ZONE" not in row["contradiction_flags"]


def test_semantic_divergence_disagreement_flags_contradiction():
    rows = compute_semantic_divergence(
        [
            _trace("t1", "gemini", "Final classification: benign.", 0, 0, 50),
            _trace("t2", "ollama", "Final classification: malicious.", 0, 0, 70),
        ]
    )
    row = rows[0]
    assert row["classification_agreement"] is False
    assert row["contradiction_detected"] is True
    assert "CLASSIFICATION_DISAGREEMENT" in row["contradiction_flags"]
