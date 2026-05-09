"""Comparative semantic divergence analysis."""

from __future__ import annotations

from itertools import combinations
from typing import Iterable

from playground_runtime.divergence.claim_overlap import claim_overlap
from playground_runtime.divergence.grounding_diff import grounding_delta
from playground_runtime.divergence.hallucination_comparison import hallucination_delta
from playground_runtime.divergence.provider_variance import provider_variance
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def _token_set(text: str) -> set[str]:
    return {t.lower() for t in text.split() if t.strip()}


def _semantic_overlap(left_text: str, right_text: str) -> float:
    lt = _token_set(left_text)
    rt = _token_set(right_text)
    union = lt | rt
    if not union:
        return 0.0
    return round(len(lt & rt) / len(union), 6)


def _citation_density_delta(left: CanonicalInferenceTrace, right: CanonicalInferenceTrace) -> float:
    left_len = max(len((left.response_text or "").split()), 1)
    right_len = max(len((right.response_text or "").split()), 1)
    left_density = len(left.citation_objects) / left_len
    right_density = len(right.citation_objects) / right_len
    return round(left_density - right_density, 6)


def compute_semantic_divergence(traces: Iterable[CanonicalInferenceTrace]) -> list[dict]:
    rows: list[dict] = []
    trace_list = list(traces)
    for left, right in combinations(trace_list, 2):
        overlap = _semantic_overlap(left.response_text or "", right.response_text or "")
        claim = claim_overlap(left.response_text or "", right.response_text or "")
        halluc_delta = hallucination_delta(left, right)
        contradiction_flags: list[str] = []
        if overlap < 0.2 and claim < 0.15:
            contradiction_flags.append("LOW_OVERLAP_CONTRADICTION_ZONE")
        rows.append(
            {
                "prompt_sha256": left.prompt_sha256,
                "left_trace_id": left.trace_id,
                "right_trace_id": right.trace_id,
                "semantic_overlap": overlap,
                "claim_overlap": claim,
                "grounding_delta": grounding_delta(left, right),
                "citation_density_delta": _citation_density_delta(left, right),
                "hallucination_delta": halluc_delta,
                "contradiction_flags": contradiction_flags,
                "provider_variance": provider_variance(left, right),
            }
        )
    return rows
