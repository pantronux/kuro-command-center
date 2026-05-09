from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

_LABEL_RE = re.compile(r"\[(?:VERIFIED:[^\]]+|INFERRED|SPECULATIVE|UNKNOWN)\]\s*", re.IGNORECASE)
_RETRIEVAL_BLOCK_RE = re.compile(r"\[RETRIEVAL QUALITY:[^\]]+\].*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL)

# Internal/policy markers that must never be streamed to users.
_INTERNAL_MARKERS: tuple[str, ...] = (
    "EPISTEMIC ACCOUNTABILITY LAYER",
    "MANDATORY CLAIM LABELING GRAMMAR",
    "HARD RULES",
    "[CHAIN OF THOUGHT",
    "[RAW TELEMETRY",
    "[INTERNAL",
    "memory_coordinator",
    "kuro_intelligence.db",
    "source_provenance",
)

_COT_BLOCK_RE = re.compile(
    r"\[CHAIN OF THOUGHT[^\]]*\].*?(?=\n\n[A-Z\[]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

_JSON_TELEMETRY_RE = re.compile(
    r"\{\s*\"(?:session_id|trace_id|confidence_score|retrieval_grade|epistemic_labels)\".*?\}",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class SanitizationResult:
    text: str
    blocked: bool
    reason: str = ""


class ResponseSanitizer:
    """Hard gate that removes internal metadata from user-facing text."""

    def strip_internal_labels(self, text: str) -> str:
        if not text:
            return ""
        clean = _LABEL_RE.sub("", text)
        clean = _RETRIEVAL_BLOCK_RE.sub("", clean)
        return clean

    def normalize_uncertainty_language(self, text: str) -> str:
        if not text:
            return ""
        replacements = {
            "I cannot verify": "I do not have enough grounded evidence",
            "not verified": "not fully confirmed",
            "parametric": "model-based",
            "accuracy is not guaranteed": "this may be incomplete",
        }
        out = text
        for src, dst in replacements.items():
            out = out.replace(src, dst)
        return out

    def sanitize_chain_of_thought(self, text: str) -> str:
        if not text:
            return ""
        clean = _COT_BLOCK_RE.sub("", text)
        clean = _JSON_TELEMETRY_RE.sub("", clean)
        return clean

    def _contains_internal_markers(self, text: str) -> str:
        low = text.lower()
        for marker in _INTERNAL_MARKERS:
            if marker.lower() in low:
                return marker
        return ""

    def validate_user_safe_output(self, text: str) -> SanitizationResult:
        marker = self._contains_internal_markers(text)
        if marker:
            return SanitizationResult(text="", blocked=True, reason=f"internal_marker:{marker}")

        # Block raw dict-like telemetry lines that survived regex pass.
        for line in text.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if line_stripped.startswith("{") and line_stripped.endswith("}"):
                try:
                    payload = json.loads(line_stripped)
                    if isinstance(payload, dict) and any(
                        k in payload for k in ("trace_id", "session_id", "epistemic_labels", "confidence_score")
                    ):
                        return SanitizationResult(text="", blocked=True, reason="raw_json_telemetry")
                except Exception:
                    continue

        return SanitizationResult(text=text, blocked=False)

    def sanitize_user_output(self, text: str, *, fallback: str = "") -> str:
        if not text:
            return ""
        clean = self.strip_internal_labels(text)
        clean = self.sanitize_chain_of_thought(clean)
        clean = self.normalize_uncertainty_language(clean)
        verdict = self.validate_user_safe_output(clean)
        if verdict.blocked:
            return fallback or "Maaf, saya belum punya cukup bukti yang ter-grounding untuk menjawab ini secara presisi."
        return self._normalize_spacing(clean)

    @staticmethod
    def _normalize_spacing(text: str) -> str:
        out = text.replace("\r\n", "\n")
        out = re.sub(r"\n{3,}", "\n\n", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        return out.strip()


response_sanitizer = ResponseSanitizer()
