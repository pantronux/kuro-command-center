"""Provider variance projection."""

from __future__ import annotations

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def provider_variance(left: CanonicalInferenceTrace, right: CanonicalInferenceTrace) -> dict:
    return {
        "left_provider": left.provider_id,
        "right_provider": right.provider_id,
        "token_delta": float((left.total_tokens or 0) - (right.total_tokens or 0)),
        "latency_delta_ms": float((left.latency_ms or 0.0) - (right.latency_ms or 0.0)),
    }
