"""Epistemic divergence metric."""

from typing import Iterable

from playground_runtime.forensic.epistemic_diff import compute_epistemic_diff
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def score_epistemic_divergence(traces: Iterable[CanonicalInferenceTrace]) -> float:
    diffs = compute_epistemic_diff(traces)
    if not diffs:
        return 0.0
    return sum(float(d["divergence_score"]) for d in diffs) / len(diffs)
