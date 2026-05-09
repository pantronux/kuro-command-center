"""
Compatibility facade for the legacy label-based epistemic filter.

Canvas 1 keeps this module import path stable, but the implementation is now
backed by structured internal epistemic objects and output sanitization.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional

from kuro_backend.intelligence.epistemic_engine import epistemic_engine
from kuro_backend.intelligence.response_sanitizer import response_sanitizer

logger = logging.getLogger(__name__)
logger.propagate = False


class EpistemicFilter:
    # Kept for backward compatibility with older call-sites.
    LABEL_VERIFIED_MEMORY = "[VERIFIED: memory]"
    LABEL_VERIFIED_SEARCH = "[VERIFIED: search]"
    LABEL_INFERRED = "[INFERRED]"
    LABEL_SPECULATIVE = "[SPECULATIVE]"
    LABEL_UNKNOWN = "[UNKNOWN]"

    def label_claims_in_response(
        self,
        text: str,
        *,
        retrieval_grade: str = "grounded",
        has_memory: bool = False,
        evidence_items: Optional[Iterable[object]] = None,
    ) -> str:
        """Legacy API: returns text while storing structured internal annotation."""
        if not text or not text.strip():
            return text
        annotation = epistemic_engine.annotate(
            text,
            retrieval_grade=retrieval_grade,
            has_memory=has_memory,
            evidence_items=evidence_items,
        )
        # Keep annotation accessible for audit via side channel on instance.
        self._last_annotation = annotation
        return text

    def check_hard_rules(self, text: str) -> Optional[str]:
        """Legacy API: fail closed when internal markers appear in visible text."""
        verdict = response_sanitizer.validate_user_safe_output(text)
        if verdict.blocked:
            return f"Unsafe output blocked: {verdict.reason}"
        return None

    def inject_disclaimer_if_needed(self, text: str) -> str:
        if not text:
            return ""
        ann = getattr(self, "_last_annotation", None) or {}
        conf = float(ann.get("confidence_score", 1.0) or 1.0)
        if conf < 0.35:
            return text + "\n\nSaya belum punya cukup bukti yang ter-grounding untuk memastikan jawaban ini."
        if conf < 0.55:
            return text + "\n\nJawaban ini berbasis bukti terbatas dan sebaiknya diverifikasi ulang."
        return text

    def inject_autorag_notification(self, text: str, retrieval_grade: str) -> str:
        if retrieval_grade in ("weak", "contradictory", "stale", "irrelevant", "ambiguous"):
            return text + (
                "\n\n⚠️ AutoRAG Notice: kualitas retrieval rendah; jawaban bisa parsial dan perlu verifikasi."
            )
        return text

    def count_claim_density(self, text: str) -> Dict[str, int]:
        """Legacy API: now reports internal claim counts by source type."""
        ann = getattr(self, "_last_annotation", None) or {}
        claims = ann.get("claims", []) or []
        out: Dict[str, int] = {
            "VERIFIED:memory": 0,
            "VERIFIED:search": 0,
            "INFERRED": 0,
            "SPECULATIVE": 0,
            "UNKNOWN": 0,
        }
        for claim in claims:
            source = getattr(claim, "source_type", "model")
            conf = float(getattr(claim, "confidence", 0.0) or 0.0)
            if source == "memory":
                out["VERIFIED:memory"] += 1
            elif source == "search":
                out["VERIFIED:search"] += 1
            elif conf < 0.35:
                out["UNKNOWN"] += 1
            elif conf < 0.55:
                out["SPECULATIVE"] += 1
            else:
                out["INFERRED"] += 1
        return out

    @staticmethod
    def _strip_labels(text: str) -> str:
        return re.sub(
            r"\[(?:VERIFIED:\s*[^\]]+|INFERRED|SPECULATIVE|UNKNOWN)\]\s*",
            "",
            text or "",
            flags=re.IGNORECASE,
        )

    @staticmethod
    def strip_labels(text: str) -> str:
        return response_sanitizer.sanitize_user_output(EpistemicFilter._strip_labels(text or ""))


epistemic_filter = EpistemicFilter()
