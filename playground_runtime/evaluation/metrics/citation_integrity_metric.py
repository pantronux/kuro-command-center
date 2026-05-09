"""Citation integrity metric."""

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def score_citation_integrity(trace: CanonicalInferenceTrace) -> float:
    if trace.citation_objects:
        return 1.0
    return 0.0
