"""Hallucination metric."""

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def score_hallucination(trace: CanonicalInferenceTrace) -> float:
    if not trace.response_text:
        return 0.0
    if trace.grounding_chunks:
        return 0.0
    return 1.0
