from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List

from .confidence_engine import ConfidenceSignals, compute_confidence, confidence_level
from .contradiction_detector import detect_contradictions
from .grounding_validator import extract_claims
from .provenance_tracker import build_record
from .response_sanitizer import response_sanitizer
from .uncertainty_renderer import render_uncertainty


@dataclass
class Claim:
    text: str
    source_type: str
    confidence: float
    evidence_refs: List[str] = field(default_factory=list)
    visibility: str = "internal"
    temporal_validity: str = "unknown"
    contradiction_score: float = 0.0


class EpistemicEngine:
    def annotate(
        self,
        text: str,
        *,
        retrieval_grade: str,
        has_memory: bool,
        evidence_items: Iterable[object] | None = None,
    ) -> Dict[str, Any]:
        evidence = list(evidence_items or [])
        contradiction = detect_contradictions(text, evidence)
        claims = extract_claims(text)

        memory_certainty = 0.9 if has_memory else 0.3
        retrieval_score = {
            "grounded": 0.95,
            "partial": 0.75,
            "weak": 0.50,
            "contradictory": 0.30,
            "stale": 0.40,
            "irrelevant": 0.20,
            "relevant": 0.75,
            "ambiguous": 0.45,
        }.get(retrieval_grade, 0.50)

        signals = ConfidenceSignals(
            retrieval_relevance=retrieval_score,
            semantic_similarity=min(1.0, 0.35 + (0.08 * len(claims))),
            multisource_agreement=max(0.0, 1.0 - contradiction.score),
            freshness=0.7 if has_memory else 0.4,
            memory_certainty=memory_certainty,
            tool_verification=0.5,
        )
        overall_conf = compute_confidence(signals)
        level = confidence_level(overall_conf)

        claim_objects: list[Claim] = []
        provenance: list[dict[str, str]] = []
        for c in claims:
            claim_objects.append(
                Claim(
                    text=c,
                    source_type="memory" if has_memory else "model",
                    confidence=overall_conf,
                    evidence_refs=[str(ev)[:120] for ev in evidence[:3]],
                    temporal_validity="current" if has_memory else "unknown",
                    contradiction_score=contradiction.score,
                )
            )
            provenance.append(build_record(c, "memory" if has_memory else "model").__dict__)

        uncertainty = render_uncertainty(overall_conf)
        safe_text = response_sanitizer.sanitize_user_output(text)
        if uncertainty and level in ("unsafe", "weak_evidence", "soft_inference"):
            safe_text = f"{safe_text}\n\n{uncertainty}" if safe_text else uncertainty

        return {
            "claims": claim_objects,
            "provenance": provenance,
            "confidence_score": overall_conf,
            "confidence_level": level,
            "contradiction_score": contradiction.score,
            "created_at": datetime.utcnow().isoformat(timespec="seconds"),
            "user_safe_text": safe_text,
        }


epistemic_engine = EpistemicEngine()
