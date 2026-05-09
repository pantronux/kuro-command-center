"""
Evaluator.

--- Header Doc ---
Purpose: Compute core evaluation dimensions for KPR traces.
Caller: report builder and API endpoints.
Dependencies: metric modules.
Main Functions: evaluate_traces().
Side Effects: None.
"""

from __future__ import annotations

from typing import Iterable

from playground_runtime.evaluation.metrics.citation_integrity_metric import score_citation_integrity
from playground_runtime.evaluation.metrics.grounding_metric import score_grounding
from playground_runtime.evaluation.metrics.hallucination_metric import score_hallucination
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def evaluate_traces(traces: Iterable[CanonicalInferenceTrace]) -> dict:
    rows = list(traces)
    if not rows:
        return {
            "hallucination_rate": 0.0,
            "grounding_coverage": 0.0,
            "citation_integrity": 0.0,
            "forensic_completeness": 0.0,
        }

    h_scores = [score_hallucination(t) for t in rows]
    g_scores = [score_grounding(t) for t in rows]
    c_scores = [score_citation_integrity(t) for t in rows]

    completeness = []
    for t in rows:
        fields = [t.response_text is not None, t.finish_reason is not None, t.total_tokens is not None, bool(t.provider_raw_id)]
        completeness.append(sum(1 for f in fields if f) / len(fields))

    return {
        "hallucination_rate": sum(h_scores) / len(h_scores),
        "grounding_coverage": sum(g_scores) / len(g_scores),
        "citation_integrity": sum(c_scores) / len(c_scores),
        "forensic_completeness": sum(completeness) / len(completeness),
    }
