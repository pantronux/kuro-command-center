"""Hallucination delta scoring."""

from __future__ import annotations

from playground_runtime.evaluation.metrics.hallucination_metric import score_hallucination
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def hallucination_delta(left: CanonicalInferenceTrace, right: CanonicalInferenceTrace) -> float:
    return round(score_hallucination(left) - score_hallucination(right), 6)
