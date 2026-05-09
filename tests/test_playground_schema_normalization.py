from __future__ import annotations

from copy import deepcopy

from playground_runtime.governance.reasoning_policy import split_hidden_reasoning_fields_deep
from playground_runtime.schema.mappers.gemini_mapper import GeminiMapper
from playground_runtime.schema.mappers.openai_mapper import OpenAIMapper
from playground_runtime.schema.normalization_registry import NormalizationRegistry


def _gemini_payload() -> dict:
    return {
        "provider_id": "gemini",
        "model": "models/gemini-3-flash-preview",
        "modelVersion": "gemini-3-flash-preview",
        "generationConfig": {
            "temperature": 0.25,
            "topP": 0.88,
            "topK": 48,
            "responseMimeType": "",
        },
        "tools": [{"googleSearch": {}}],
        "systemInstruction": {"parts": [{"text": "secret-system"}], "role": "user"},
        "contents": [{"parts": [{"text": "what is this"}], "role": "user"}],
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": "answer"}]},
                "groundingMetadata": {
                    "groundingChunks": [{"chunk": "a"}],
                    "webSearchQueries": ["kpr schema"],
                },
                "safetyRatings": [{"category": "safe", "probability": "LOW"}],
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 15,
            "totalTokenCount": 25,
        },
        "promptFeedback": {},
        "responseId": "r-1",
    }


def test_gemini_mapper_model_field_strip_prefix():
    mapper = GeminiMapper()
    trace = mapper.map_to_canonical("s1", "e1", "raw1", _gemini_payload())
    assert trace.model_id == "gemini-3-flash-preview"


def test_gemini_mapper_generation_config_to_extra_fields():
    mapper = GeminiMapper()
    trace = mapper.map_to_canonical("s1", "e1", "raw1", _gemini_payload())
    assert trace.extra_fields["generation_temperature"] == 0.25
    assert trace.extra_fields["generation_top_p"] == 0.88
    assert trace.extra_fields["generation_top_k"] == 48


def test_gemini_mapper_empty_mime_type_flag():
    mapper = GeminiMapper()
    trace = mapper.map_to_canonical("s1", "e1", "raw1", _gemini_payload())
    assert "MIME_TYPE_UNSET" in trace.forensic_flags


def test_gemini_mapper_grounding_tool_detection():
    mapper = GeminiMapper()
    trace = mapper.map_to_canonical("s1", "e1", "raw1", _gemini_payload())
    assert trace.extra_fields["grounding_tool"] == "googleSearch"


def test_gemini_mapper_usage_metadata_token_mapping():
    mapper = GeminiMapper()
    trace = mapper.map_to_canonical("s1", "e1", "raw1", _gemini_payload())
    assert trace.input_tokens == 10
    assert trace.output_tokens == 15
    assert trace.total_tokens == 25


def test_gemini_mapper_system_instruction_not_in_canonical():
    mapper = GeminiMapper()
    trace = mapper.map_to_canonical("s1", "e1", "raw1", _gemini_payload())
    assert "systemInstruction" not in trace.extra_fields
    assert "secret-system" not in (trace.response_text or "")
    assert all("systemInstruction" not in w for w in trace.normalization_warnings)


def test_schema_drift_flag_on_unknown_field():
    mapper = OpenAIMapper()
    raw = {
        "provider_id": "openai",
        "model_id": "gpt",
        "model_version": "gpt-v1",
        "prompt": "hello",
        "response_text": "world",
        "finish_reason": "stop",
        "unexpected_x": 123,
    }
    trace = mapper.map_to_canonical("s1", "e1", "raw1", raw)
    assert any(flag.startswith("SCHEMA_DRIFT") for flag in trace.forensic_flags)


def test_renormalize_detects_version_mismatch():
    registry = NormalizationRegistry()
    raw = _gemini_payload()
    trace = registry.renormalize(
        session_id="s1",
        execution_id="e1",
        provider_raw_id="raw1",
        raw_record=raw,
        original_schema_version="gemini/0.9.0",
    )
    assert any("SCHEMA_VERSION_MISMATCH" in w for w in trace.normalization_warnings)
    assert "SCHEMA_VERSION_MISMATCH" in trace.forensic_flags


def test_deep_reasoning_strip_nested():
    raw = {"choices": [{"message": {"reasoning": "hidden", "text": "ok"}}]}
    sanitized, warnings = split_hidden_reasoning_fields_deep(raw)
    assert "reasoning" not in sanitized["choices"][0]["message"]
    assert any(w.startswith("HIDDEN_REASONING_FIELDS_STRIPPED_NESTED:") for w in warnings)


def test_unknown_provider_fallback_warning():
    registry = NormalizationRegistry()
    raw = {
        "provider_id": "future_provider_xyz",
        "model_id": "future",
        "model_version": "1",
        "prompt": "hello",
        "response_text": "hi",
        "finish_reason": "stop",
    }
    trace = registry.normalize("s1", "e1", "raw1", raw)
    assert trace.schema_version == "unknown/fallback/1.0.0"
    assert "UNKNOWN_PROVIDER:future_provider_xyz" in trace.normalization_warnings
    assert "UNKNOWN_PROVIDER" in trace.forensic_flags


def test_raw_evidence_not_mutated_after_normalize():
    registry = NormalizationRegistry()
    raw = _gemini_payload()
    original = deepcopy(raw)
    _ = registry.normalize("s1", "e1", "raw1", raw)
    assert raw == original
