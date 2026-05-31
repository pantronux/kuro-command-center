from __future__ import annotations

from datetime import datetime, timezone

from playground_runtime.integrity.transformation_manifest import build_transformation_manifest
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def test_transformation_manifest_has_candidates_and_flags():
    trace = CanonicalInferenceTrace(
        trace_id="t1",
        session_id="s1",
        execution_id="e1",
        provider_id="openai",
        model_id="m",
        model_version="v",
        schema_version="openai/1.0.0",
        prompt_sha256="p",
        dataset_version=None,
        collected_at_utc=datetime.now(timezone.utc),
        response_text="hello",
        finish_reason="stop",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        latency_ms=1.0,
        grounding_chunks=[],
        citation_objects=[],
        safety_ratings=None,
        provider_raw_id="r1",
        forensic_flags=[],
        normalization_warnings=["SCHEMA_DRIFT:grounding_chunks"],
        extra_fields={},
    )
    manifest = build_transformation_manifest(
        source_hash="a",
        target_hash="b",
        transformer_version="openai/1.0.0",
        raw_record={"grounding_chunks": [{"x": 1}], "reasoning": "hidden"},
        trace=trace,
    )
    assert manifest["source_hash"] == "a"
    assert manifest["target_hash"] == "b"
    assert manifest["mapping_confidence"] > 0.0
    assert len(manifest["canonical_candidates"]) >= 1
    assert "UNMAPPED_FIELDS" in manifest["semantic_loss_flags"]
