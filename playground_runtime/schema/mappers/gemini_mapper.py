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

from playground_runtime.schema.drift_classifier import (
    classify_projection_drift,
    classify_provider_field_preservation,
    has_value,
)
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
        "id",
        "object",
        "created",
        "choices",
        "usage",
        # Internal normalization metadata used in runtime pipeline:
        "provider_id",
        "dataset_version",
        "latency_ms",
        "collected_at_utc",
        "prompt",
        "model_id",
        "model_version",
        "response_text",
        "finish_reason",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "provider_response_id",
        "provider_response_object",
        "provider_response_created",
        "provider_response_model",
        "system_fingerprint",
        "visible_reasoning_trace",
        "visible_reasoning_trace_origin",
        "provider_specific_artifact_type",
        "provider_specific_artifact_origin",
        "provider_specific_artifact_human_readable",
        "provider_thought_signature",
        "reasoning_signature_origin",
        "grounding_chunks",
        "citation_objects",
        "safety_ratings",
    }

    @staticmethod
    def _coalesce(*values):
        for value in values:
            if has_value(value):
                return value
        return None

    def map_to_canonical(self, session_id, execution_id, provider_raw_id, raw_record):
        raw = raw_record.copy()
        warnings: list[str] = []

        model_raw = self._coalesce(
            raw.get("model"),
            raw.get("provider_response_model"),
            raw.get("model_id"),
            raw.get("modelVersion"),
            raw.get("model_version"),
        )
        model_raw = str(model_raw or "")
        model_id_raw = self._coalesce(raw.get("model_id"), model_raw, raw.get("modelVersion"))
        model_id = str(model_id_raw or "unknown").removeprefix("models/")
        model_version = str(self._coalesce(raw.get("model_version"), model_raw, raw.get("modelVersion")) or "unknown")

        generation_config = raw.get("generationConfig") if isinstance(raw.get("generationConfig"), dict) else {}
        tools = raw.get("tools") if isinstance(raw.get("tools"), list) else []
        candidates = raw.get("candidates") if isinstance(raw.get("candidates"), list) else []
        usage = raw.get("usageMetadata") if isinstance(raw.get("usageMetadata"), dict) else {}
        openai_usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        choices = raw.get("choices") if isinstance(raw.get("choices"), list) else []

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
        elif tools:
            warnings.append("GROUNDING_TOOL_ABSENT")

        response_text = raw.get("response_text")
        finish_reason = raw.get("finish_reason")
        grounding_chunks = raw.get("grounding_chunks") if isinstance(raw.get("grounding_chunks"), list) else []
        citation_objects = raw.get("citation_objects") if isinstance(raw.get("citation_objects"), list) else []
        safety_ratings = raw.get("safety_ratings") if isinstance(raw.get("safety_ratings"), dict) else None
        input_tokens = raw.get("input_tokens")
        output_tokens = raw.get("output_tokens")
        total_tokens = raw.get("total_tokens")
        provider_response_id = raw.get("provider_response_id")
        provider_response_object = raw.get("provider_response_object")
        provider_response_created = raw.get("provider_response_created")
        provider_response_model = raw.get("provider_response_model")

        first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        first_choice_message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
        choice_content = first_choice_message.get("content")
        choice_finish = first_choice.get("finish_reason")
        if not has_value(response_text):
            response_text = choice_content
        if not has_value(finish_reason):
            finish_reason = choice_finish

        if not has_value(input_tokens):
            input_tokens = openai_usage.get("prompt_tokens")
        if not has_value(output_tokens):
            output_tokens = openai_usage.get("completion_tokens")
        if not has_value(total_tokens):
            total_tokens = openai_usage.get("total_tokens")

        if not has_value(provider_response_id):
            provider_response_id = raw.get("id")
        if not has_value(provider_response_object):
            provider_response_object = raw.get("object")
        if not has_value(provider_response_created):
            provider_response_created = raw.get("created")
        if not has_value(provider_response_model):
            provider_response_model = raw.get("model")

        native_response_text = None
        native_finish_reason = None
        native_grounding_chunks = []
        native_citations = []
        native_safety = None
        if candidates:
            candidate0 = candidates[0] if isinstance(candidates[0], dict) else {}
            native_finish_reason = candidate0.get("finishReason")
            content = candidate0.get("content") if isinstance(candidate0.get("content"), dict) else {}
            parts = content.get("parts") if isinstance(content.get("parts"), list) else []
            if parts and isinstance(parts[0], dict):
                native_response_text = parts[0].get("text")
            grounding_metadata = (
                candidate0.get("groundingMetadata")
                if isinstance(candidate0.get("groundingMetadata"), dict)
                else {}
            )
            if isinstance(grounding_metadata.get("groundingChunks"), list):
                native_grounding_chunks = grounding_metadata.get("groundingChunks") or []
            if isinstance(grounding_metadata.get("webSearchQueries"), list):
                native_citations = [
                    {"query": q}
                    for q in grounding_metadata.get("webSearchQueries")
                ]
            if isinstance(candidate0.get("safetyRatings"), list):
                native_safety = {"ratings": candidate0.get("safetyRatings")}

        if not has_value(response_text):
            response_text = native_response_text
        if not has_value(finish_reason):
            finish_reason = native_finish_reason
        if not has_value(input_tokens):
            input_tokens = usage.get("promptTokenCount")
        if not has_value(output_tokens):
            output_tokens = usage.get("candidatesTokenCount")
        if not has_value(total_tokens):
            total_tokens = usage.get("totalTokenCount")
        if not grounding_chunks:
            grounding_chunks = native_grounding_chunks
        if not citation_objects:
            citation_objects = native_citations
        if safety_ratings is None:
            safety_ratings = native_safety

        if not candidates and not choices:
            warnings.append("NO_CANDIDATES")
        if not grounding_chunks:
            warnings.append("GROUNDING_ABSENT")

        finish_norm = (str(finish_reason).strip().lower() if finish_reason is not None else "")
        if finish_norm and finish_norm not in {"stop", "max_tokens", "end_turn", "completed"}:
            warnings.append("FINISH_REASON_ABNORMAL")

        thought_signature = raw.get("provider_thought_signature")
        if not has_value(thought_signature) and isinstance(first_choice_message, dict):
            extra_content = first_choice_message.get("extra_content")
            if isinstance(extra_content, dict):
                google_meta = extra_content.get("google")
                if isinstance(google_meta, dict):
                    thought_signature = google_meta.get("thought_signature")
        if has_value(thought_signature):
            extra_fields["provider_thought_signature"] = thought_signature
            extra_fields["provider_specific_artifact_type"] = "opaque_reasoning_signature"
            extra_fields["provider_specific_artifact_origin"] = "provider_opaque_artifact"
            extra_fields["provider_specific_artifact_human_readable"] = False
            extra_fields["reasoning_signature_origin"] = "provider_opaque_artifact"

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

        warnings.extend(
            classify_projection_drift(
                canonical_fields={
                    "model_id": model_id,
                    "model_version": model_version,
                    "response_text": response_text,
                    "finish_reason": finish_reason,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                },
                source_candidates={
                    "model_id": [raw.get("model_id"), raw.get("model"), raw.get("provider_response_model"), raw.get("modelVersion")],
                    "model_version": [raw.get("model_version"), raw.get("model"), raw.get("provider_response_model"), raw.get("modelVersion")],
                    "response_text": [raw.get("response_text"), choice_content, native_response_text],
                    "finish_reason": [raw.get("finish_reason"), choice_finish, native_finish_reason],
                    "input_tokens": [raw.get("input_tokens"), openai_usage.get("prompt_tokens"), usage.get("promptTokenCount")],
                    "output_tokens": [raw.get("output_tokens"), openai_usage.get("completion_tokens"), usage.get("candidatesTokenCount")],
                    "total_tokens": [raw.get("total_tokens"), openai_usage.get("total_tokens"), usage.get("totalTokenCount")],
                },
            )
        )
        warnings.extend(
            classify_provider_field_preservation(
                provider_fields={"provider_thought_signature": thought_signature},
                preserved_fields=extra_fields,
            )
        )
        for key, value in (
            ("provider_response_id", provider_response_id),
            ("provider_response_object", provider_response_object),
            ("provider_response_created", provider_response_created),
            ("provider_response_model", provider_response_model),
        ):
            if has_value(value):
                extra_fields[key] = value

        unique_warnings: list[str] = []
        seen = set()
        for warning in warnings:
            if warning in seen:
                continue
            seen.add(warning)
            unique_warnings.append(warning)

        return CanonicalInferenceTrace(
            trace_id=str(uuid4()),
            session_id=session_id,
            execution_id=execution_id,
            provider_id=raw.get("provider_id", "gemini"),
            model_id=model_id or "unknown",
            model_version=model_version or "unknown",
            schema_version=self.schema_version,
            prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
            dataset_version=raw.get("dataset_version"),
            collected_at_utc=collected_at,
            response_text=response_text,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=raw.get("latency_ms"),
            grounding_chunks=grounding_chunks,
            citation_objects=citation_objects,
            safety_ratings=safety_ratings,
            provider_raw_id=provider_raw_id,
            forensic_flags=self._extract_forensic_flags(unique_warnings),
            normalization_warnings=unique_warnings,
            extra_fields=extra_fields,
        )
