"""Grounding metric."""

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def score_grounding(trace: CanonicalInferenceTrace) -> float:
    return 1.0 if trace.grounding_chunks else 0.0
