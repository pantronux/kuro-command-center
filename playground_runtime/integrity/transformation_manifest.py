"""Transformation manifest for raw->canonical normalization lineage."""

from __future__ import annotations

from typing import Any

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace

_CANDIDATE_MAP = {
    "grounding_chunks": "evidence_grounding_artifact",
    "citations": "citation_objects",
    "citation_objects": "citation_objects",
    "reasoning": "reasoning_artifact",
}


def _collect_semantic_loss_flags(trace: CanonicalInferenceTrace) -> list[str]:
    flags: list[str] = []
    for warning in trace.normalization_warnings:
        if warning.startswith("SCHEMA_DRIFT"):
            flags.append("UNMAPPED_FIELDS")
        if warning.startswith("UNKNOWN_PROVIDER"):
            flags.append("UNRESOLVED_PROVIDER_ALIAS")
        if warning.startswith("HIDDEN_REASONING"):
            flags.append("REASONING_REDACTED")
    if not trace.grounding_chunks:
        flags.append("GROUNDING_ABSENT")
    return sorted(set(flags))


def _collect_schema_drift_flags(trace: CanonicalInferenceTrace) -> list[str]:
    return sorted({w for w in trace.normalization_warnings if w.startswith("SCHEMA_DRIFT")})


def _candidate_layer(raw_record: dict[str, Any]) -> tuple[list[dict], dict[str, str]]:
    candidates: list[dict] = []
    aliases: dict[str, str] = {}
    for key, value in raw_record.items():
        if key not in _CANDIDATE_MAP:
            continue
        target = _CANDIDATE_MAP[key]
        confidence = 0.84 if value else 0.5
        candidates.append(
            {
                "provider_field": key,
                "candidate_canonical_field": target,
                "mapping_confidence": round(confidence, 2),
            }
        )
        aliases[key] = target
    return candidates, aliases


def build_transformation_manifest(
    *,
    source_hash: str,
    target_hash: str,
    transformer_version: str,
    raw_record: dict[str, Any],
    trace: CanonicalInferenceTrace,
) -> dict:
    candidates, alias_map = _candidate_layer(raw_record)
    confidences = [float(c["mapping_confidence"]) for c in candidates]
    confidence = 0.91 if not confidences else round(sum(confidences) / len(confidences), 2)
    return {
        "source_hash": source_hash,
        "target_hash": target_hash,
        "transformer_version": transformer_version,
        "mapping_confidence": confidence,
        "semantic_loss_flags": _collect_semantic_loss_flags(trace),
        "schema_drift_flags": _collect_schema_drift_flags(trace),
        "canonical_candidates": candidates,
        "provider_alias_mapping": alias_map,
    }
