"""
Gemini mapper.

--- Header Doc ---
Purpose: Normalize Gemini payloads using Gemini-specific field mapping.
Caller: normalization registry.
Dependencies: datetime, hashlib, uuid, openai mapper base behavior.
Main Functions: GeminiMapper.map_to_canonical().
Side Effects: None.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace
from playground_runtime.schema.mappers.openai_mapper import OpenAIMapper


class GeminiMapper(OpenAIMapper):
    schema_version = "gemini/1.0.0"
    GEMINI_KNOWN_FIELDS = {
        "model",
        "contents",
        "generationConfig",
        "systemInstruction",
        "tools",
        "candidates",
        "usageMetadata",
        "promptFeedback",
        "modelVersion",
        "createTime",
        "responseId",
        # Internal normalization metadata used in runtime pipeline:
        "provider_id",
        "dataset_version",
        "latency_ms",
        "collected_at_utc",
        "prompt",
    }

    def map_to_canonical(self, session_id, execution_id, provider_raw_id, raw_record):
        raw = raw_record.copy()
        warnings: list[str] = []

        model_raw = str(raw.get("model") or "")
        model_id = model_raw.removeprefix("models/") if model_raw else str(raw.get("modelVersion") or "unknown")

        generation_config = raw.get("generationConfig") if isinstance(raw.get("generationConfig"), dict) else {}
        tools = raw.get("tools") if isinstance(raw.get("tools"), list) else []
        candidates = raw.get("candidates") if isinstance(raw.get("candidates"), list) else []
        usage = raw.get("usageMetadata") if isinstance(raw.get("usageMetadata"), dict) else {}

        extra_fields, drift_warnings = self.collect_unknown_fields(raw, self.GEMINI_KNOWN_FIELDS)
        warnings.extend(drift_warnings)

        extra_fields["generation_temperature"] = generation_config.get("temperature")
        extra_fields["generation_top_p"] = generation_config.get("topP")
        extra_fields["generation_top_k"] = generation_config.get("topK")
        extra_fields["response_mime_type"] = generation_config.get("responseMimeType")
        if generation_config.get("responseMimeType", None) == "":
            warnings.append("MIME_TYPE_UNSET")

        has_google_search = any(
            isinstance(tool, dict) and "googleSearch" in tool
            for tool in tools
        )
        if has_google_search:
            extra_fields["grounding_tool"] = "googleSearch"
        else:
            warnings.append("GROUNDING_TOOL_ABSENT")

        response_text = None
        finish_reason = None
        grounding_chunks = []
        citation_objects = []
        safety_ratings = None

        if not candidates:
            warnings.append("NO_CANDIDATES")
        else:
            candidate0 = candidates[0] if isinstance(candidates[0], dict) else {}
            finish_reason = candidate0.get("finishReason")
            finish_norm = (str(finish_reason).strip().upper() if finish_reason is not None else "")
            if finish_norm and finish_norm not in {"STOP", "MAX_TOKENS"}:
                warnings.append("FINISH_REASON_ABNORMAL")
            content = candidate0.get("content") if isinstance(candidate0.get("content"), dict) else {}
            parts = content.get("parts") if isinstance(content.get("parts"), list) else []
            if parts and isinstance(parts[0], dict):
                response_text = parts[0].get("text")
            grounding_metadata = (
                candidate0.get("groundingMetadata")
                if isinstance(candidate0.get("groundingMetadata"), dict)
                else {}
            )
            if isinstance(grounding_metadata.get("groundingChunks"), list):
                grounding_chunks = grounding_metadata.get("groundingChunks") or []
            if isinstance(grounding_metadata.get("webSearchQueries"), list):
                citation_objects = [
                    {"query": q}
                    for q in grounding_metadata.get("webSearchQueries")
                ]
            if isinstance(candidate0.get("safetyRatings"), list):
                safety_ratings = {"ratings": candidate0.get("safetyRatings")}

        if not grounding_chunks:
            warnings.append("GROUNDING_ABSENT")

        prompt = raw.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = ""
            contents = raw.get("contents") if isinstance(raw.get("contents"), list) else []
            if contents and isinstance(contents[0], dict):
                first_parts = contents[0].get("parts") if isinstance(contents[0].get("parts"), list) else []
                if first_parts and isinstance(first_parts[0], dict):
                    prompt = str(first_parts[0].get("text") or "")

        collected_at = raw.get("collected_at_utc")
        if not isinstance(collected_at, datetime):
            collected_at = datetime.now(timezone.utc)

        return CanonicalInferenceTrace(
            trace_id=str(uuid4()),
            session_id=session_id,
            execution_id=execution_id,
            provider_id=raw.get("provider_id", "gemini"),
            model_id=model_id or "unknown",
            model_version=str(raw.get("modelVersion") or model_raw or "unknown"),
            schema_version=self.schema_version,
            prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
            dataset_version=raw.get("dataset_version"),
            collected_at_utc=collected_at,
            response_text=response_text,
            finish_reason=finish_reason,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            total_tokens=usage.get("totalTokenCount"),
            latency_ms=raw.get("latency_ms"),
            grounding_chunks=grounding_chunks,
            citation_objects=citation_objects,
            safety_ratings=safety_ratings,
            provider_raw_id=provider_raw_id,
            forensic_flags=self._extract_forensic_flags(warnings),
            normalization_warnings=warnings,
            extra_fields=extra_fields,
        )
