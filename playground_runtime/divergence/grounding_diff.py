"""Grounding delta scoring."""

from __future__ import annotations

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def grounding_delta(left: CanonicalInferenceTrace, right: CanonicalInferenceTrace) -> float:
    return float(len(left.grounding_chunks) - len(right.grounding_chunks))
