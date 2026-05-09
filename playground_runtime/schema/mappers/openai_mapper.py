"""
OpenAI mapper.

--- Header Doc ---
Purpose: Normalize OpenAI-style provider payload into CanonicalInferenceTrace.
Caller: normalization registry.
Dependencies: datetime, uuid, base mapper.
Main Functions: OpenAIMapper.map_to_canonical().
Side Effects: None.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from playground_runtime.governance.reasoning_policy import split_hidden_reasoning_fields_deep
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace
from playground_runtime.schema.mappers.base_mapper import BaseMapper


class OpenAIMapper(BaseMapper):
    schema_version = "openai/1.0.0"
    FORENSIC_FLAG_PREFIXES = {
        "GROUNDING",
        "HIDDEN_REASONING",
        "FINISH_REASON",
        "MIME_TYPE",
        "NO_CANDIDATES",
        "SCHEMA_DRIFT",
    }

    def _extract_forensic_flags(self, warnings: list[str]) -> list[str]:
        return [
            warning
            for warning in warnings
            if any(warning.startswith(prefix) for prefix in self.FORENSIC_FLAG_PREFIXES)
        ]

    def map_to_canonical(self, session_id, execution_id, provider_raw_id, raw_record):
        sanitized_raw, reasoning_warnings = split_hidden_reasoning_fields_deep(raw_record)
        raw_record = sanitized_raw
        prompt = raw_record.get("prompt", "")
        response_text = raw_record.get("response_text")
        finish_reason = raw_record.get("finish_reason")
        known = {
            "provider_id", "model_id", "model_version", "prompt", "response_text", "finish_reason",
            "input_tokens", "output_tokens", "total_tokens", "latency_ms", "collected_at_utc",
            "grounding_chunks", "citation_objects", "safety_ratings", "dataset_version",
        }
        extras, warnings = self.collect_unknown_fields(raw_record, known)
        warnings.extend(reasoning_warnings)

        if not raw_record.get("grounding_chunks"):
            warnings.append("GROUNDING_ABSENT")
        finish_reason_l = (finish_reason or "").strip().lower()
        if finish_reason_l and finish_reason_l not in {"stop", "end_turn", "completed"}:
            warnings.append("FINISH_REASON_ABNORMAL")

        return CanonicalInferenceTrace(
            trace_id=str(uuid4()),
            session_id=session_id,
            execution_id=execution_id,
            provider_id=raw_record.get("provider_id", "openai"),
            model_id=raw_record.get("model_id", "unknown"),
            model_version=raw_record.get("model_version", "unknown"),
            schema_version=self.schema_version,
            prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
            dataset_version=raw_record.get("dataset_version"),
            collected_at_utc=raw_record.get("collected_at_utc", datetime.now(timezone.utc)),
            response_text=response_text,
            finish_reason=finish_reason,
            input_tokens=raw_record.get("input_tokens"),
            output_tokens=raw_record.get("output_tokens"),
            total_tokens=raw_record.get("total_tokens"),
            latency_ms=raw_record.get("latency_ms"),
            grounding_chunks=raw_record.get("grounding_chunks") or [],
            citation_objects=raw_record.get("citation_objects") or [],
            safety_ratings=raw_record.get("safety_ratings"),
            provider_raw_id=provider_raw_id,
            forensic_flags=self._extract_forensic_flags(warnings),
            normalization_warnings=warnings,
            extra_fields=extras,
        )
