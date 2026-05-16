"""Comparative semantic divergence analysis."""

from __future__ import annotations

import re
from itertools import combinations
from typing import Iterable

from playground_runtime.divergence.claim_overlap import claim_overlap
from playground_runtime.divergence.grounding_diff import grounding_delta
from playground_runtime.divergence.hallucination_comparison import hallucination_delta
from playground_runtime.divergence.provider_variance import provider_variance
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace

_MALICIOUS_MARKERS = {
    "malicious",
    "prompt injection",
    "ignore previous instructions",
    "reveal the hidden system prompt",
    "system prompt leakage",
    "bypass safeguards",
    "unauthorized access",
    "security risk",
}
_SUSPICIOUS_MARKERS = {
    "suspicious",
    "potentially harmful",
    "needs review",
    "uncertain",
}
_BENIGN_MARKERS = {
    "benign",
    "safe",
    "not malicious",
}
_RATIONALE_CONCEPTS = {
    "prompt_injection": ("prompt injection",),
    "ignore_previous_instructions": ("ignore previous instructions",),
    "reveal_system_prompt": ("reveal the hidden system prompt", "reveal system prompt"),
    "system_prompt_leakage": ("system prompt leakage", "hidden system prompt"),
    "bypass_safeguards": ("bypass safeguards", "bypass safety"),
    "unauthorized_access": ("unauthorized access",),
    "internal_configuration": ("internal configuration",),
    "security_risk": ("security risk",),
}


def _token_set(text: str) -> set[str]:
    return {t.lower() for t in re.split(r"\\s+", text) if t.strip()}


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


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _classification_label(text: str) -> str:
    normalized = _normalize_text(text)
    if any(marker in normalized for marker in _MALICIOUS_MARKERS):
        return "malicious"
    if any(marker in normalized for marker in _SUSPICIOUS_MARKERS):
        return "suspicious"
    if any(marker in normalized for marker in _BENIGN_MARKERS):
        return "benign"
    return "unknown"


def _concept_hits(text: str) -> set[str]:
    normalized = _normalize_text(text)
    hits = set()
    for concept, markers in _RATIONALE_CONCEPTS.items():
        if any(marker in normalized for marker in markers):
            hits.add(concept)
    return hits


def _ratio_delta(left: int, right: int) -> int:
    return left - right


def _metadata_surface(trace: CanonicalInferenceTrace) -> set[str]:
    surface = set()
    extra = trace.extra_fields if isinstance(trace.extra_fields, dict) else {}
    for key in (
        "provider_response_id",
        "provider_response_object",
        "provider_response_created",
        "provider_response_model",
        "system_fingerprint",
        "visible_reasoning_trace",
        "provider_thought_signature",
        "provider_specific_artifact_type",
    ):
        value = extra.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        surface.add(key)
    return surface


def compute_semantic_divergence(traces: Iterable[CanonicalInferenceTrace]) -> list[dict]:
    rows: list[dict] = []
    trace_list = list(traces)
    for left, right in combinations(trace_list, 2):
        left_text = left.response_text or ""
        right_text = right.response_text or ""
        overlap = _semantic_overlap(left_text, right_text)
        claim = claim_overlap(left_text, right_text)
        left_label = _classification_label(left_text)
        right_label = _classification_label(right_text)
        classification_agreement = left_label == right_label and left_label != "unknown"
        contradiction_detected = left_label != right_label and left_label != "unknown" and right_label != "unknown"

        left_concepts = _concept_hits(left_text)
        right_concepts = _concept_hits(right_text)
        concept_union = left_concepts | right_concepts
        rationale_overlap = round(len(left_concepts & right_concepts) / len(concept_union), 6) if concept_union else 0.0

        left_len = len(left_text)
        right_len = len(right_text)
        left_has_visible_reasoning = bool((left.extra_fields or {}).get("visible_reasoning_trace"))
        right_has_visible_reasoning = bool((right.extra_fields or {}).get("visible_reasoning_trace"))
        visible_reasoning_delta = left_has_visible_reasoning != right_has_visible_reasoning

        left_artifact_type = (left.extra_fields or {}).get("provider_specific_artifact_type")
        right_artifact_type = (right.extra_fields or {}).get("provider_specific_artifact_type")
        provider_specific_artifact_delta = left_artifact_type != right_artifact_type

        left_surface = _metadata_surface(left)
        right_surface = _metadata_surface(right)
        metadata_delta = {
            "left_only": sorted(left_surface - right_surface),
            "right_only": sorted(right_surface - left_surface),
            "delta_count": len(left_surface ^ right_surface),
        }

        halluc_delta = hallucination_delta(left, right)
        contradiction_flags: list[str] = []
        if contradiction_detected:
            contradiction_flags.append("CLASSIFICATION_DISAGREEMENT")
        elif not classification_agreement and overlap < 0.2 and claim < 0.15:
            contradiction_flags.append("LOW_OVERLAP_CONTRADICTION_ZONE")
        variance_payload = provider_variance(left, right)
        variance_payload.update(
            {
                "classification_label_left": left_label,
                "classification_label_right": right_label,
                "classification_agreement": classification_agreement,
                "rationale_overlap": rationale_overlap,
                "output_length_left": left_len,
                "output_length_right": right_len,
                "output_length_delta": _ratio_delta(left_len, right_len),
                "token_delta": float((left.total_tokens or 0) - (right.total_tokens or 0)),
                "latency_delta_ms": float((left.latency_ms or 0.0) - (right.latency_ms or 0.0)),
                "metadata_surface_delta": metadata_delta,
                "visible_reasoning_delta": visible_reasoning_delta,
                "left_has_visible_reasoning": left_has_visible_reasoning,
                "right_has_visible_reasoning": right_has_visible_reasoning,
                "provider_specific_artifact_delta": provider_specific_artifact_delta,
                "left_provider_specific_artifact_type": left_artifact_type,
                "right_provider_specific_artifact_type": right_artifact_type,
                "left_rationale_concepts": sorted(left_concepts),
                "right_rationale_concepts": sorted(right_concepts),
                "contradiction_detected": contradiction_detected,
            }
        )
        rows.append(
            {
                "prompt_sha256": left.prompt_sha256,
                "left_trace_id": left.trace_id,
                "right_trace_id": right.trace_id,
                "semantic_overlap": overlap,
                "claim_overlap": claim,
                "classification_label_left": left_label,
                "classification_label_right": right_label,
                "classification_agreement": classification_agreement,
                "rationale_overlap": rationale_overlap,
                "output_length_delta": _ratio_delta(left_len, right_len),
                "token_delta": float((left.total_tokens or 0) - (right.total_tokens or 0)),
                "latency_delta_ms": float((left.latency_ms or 0.0) - (right.latency_ms or 0.0)),
                "metadata_surface_delta": metadata_delta,
                "visible_reasoning_delta": visible_reasoning_delta,
                "provider_specific_artifact_delta": provider_specific_artifact_delta,
                "contradiction_detected": contradiction_detected,
                "grounding_delta": grounding_delta(left, right),
                "citation_density_delta": _citation_density_delta(left, right),
                "hallucination_delta": halluc_delta,
                "contradiction_flags": contradiction_flags,
                "provider_variance": variance_payload,
            }
        )
    return rows
