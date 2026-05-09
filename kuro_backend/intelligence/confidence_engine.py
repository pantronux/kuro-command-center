from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceSignals:
    retrieval_relevance: float = 0.0
    semantic_similarity: float = 0.0
    multisource_agreement: float = 0.0
    freshness: float = 0.0
    memory_certainty: float = 0.0
    tool_verification: float = 0.0


WEIGHTS = {
    "retrieval_relevance": 0.25,
    "semantic_similarity": 0.20,
    "multisource_agreement": 0.20,
    "freshness": 0.10,
    "memory_certainty": 0.10,
    "tool_verification": 0.15,
}


def compute_confidence(signals: ConfidenceSignals) -> float:
    score = (
        signals.retrieval_relevance * WEIGHTS["retrieval_relevance"]
        + signals.semantic_similarity * WEIGHTS["semantic_similarity"]
        + signals.multisource_agreement * WEIGHTS["multisource_agreement"]
        + signals.freshness * WEIGHTS["freshness"]
        + signals.memory_certainty * WEIGHTS["memory_certainty"]
        + signals.tool_verification * WEIGHTS["tool_verification"]
    )
    return max(0.0, min(1.0, score))


def confidence_level(score: float) -> str:
    if score >= 0.90:
        return "grounded"
    if score >= 0.75:
        return "reliable"
    if score >= 0.55:
        return "soft_inference"
    if score >= 0.35:
        return "weak_evidence"
    return "unsafe"
