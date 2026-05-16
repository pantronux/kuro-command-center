"""
Normalization registry.

--- Header Doc ---
Purpose: Resolve mapper by provider_id and normalize raw evidence records.
Caller: execution pipeline.
Dependencies: mapper modules.
Main Functions: normalize().
Side Effects: None.
"""

from __future__ import annotations

from typing import Dict

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace
from playground_runtime.schema.mappers import AnthropicMapper, DeepSeekMapper, GeminiMapper, OpenAIMapper
from playground_runtime.schema.mappers.base_mapper import BaseMapper


class _UnknownProviderMapper(OpenAIMapper):
    schema_version = "unknown/fallback/1.0.0"

    def __init__(self, provider_id: str):
        self._provider_id = provider_id

    def map_to_canonical(
        self,
        session_id: str,
        execution_id: str,
        provider_raw_id: str,
        raw_record: dict,
    ) -> CanonicalInferenceTrace:
        normalized = super().map_to_canonical(
            session_id=session_id,
            execution_id=execution_id,
            provider_raw_id=provider_raw_id,
            raw_record=raw_record,
        )
        warning = f"UNKNOWN_PROVIDER:{self._provider_id}"
        normalized.normalization_warnings.append(warning)
        normalized.forensic_flags.append("UNKNOWN_PROVIDER")
        return normalized


class NormalizationRegistry:
    def __init__(self):
        self._mappers: Dict[str, BaseMapper] = {
            "openai": OpenAIMapper(),
            "gemini": GeminiMapper(),
            "anthropic": AnthropicMapper(),
            "claude": AnthropicMapper(),
            "deepseek": DeepSeekMapper(),
            "ollama": OpenAIMapper(),
            "openai_compat": OpenAIMapper(),
        }

    def register(self, provider_id: str, mapper: BaseMapper) -> None:
        self._mappers[provider_id] = mapper

    def get(self, provider_id: str) -> BaseMapper:
        mapper = self._mappers.get(provider_id)
        if mapper is None:
            return _UnknownProviderMapper(provider_id=provider_id)
        return mapper

    def normalize(self, session_id: str, execution_id: str, provider_raw_id: str, raw_record: dict) -> CanonicalInferenceTrace:
        provider_id = raw_record.get("provider_id", "openai")
        mapper = self.get(provider_id)
        return mapper.map_to_canonical(session_id, execution_id, provider_raw_id, raw_record.copy())

    def renormalize(
        self,
        session_id: str,
        execution_id: str,
        provider_raw_id: str,
        raw_record: dict,
        original_schema_version: str,
    ) -> CanonicalInferenceTrace:
        """
        Re-normalize raw_evidence using current mapper implementation.
        Adds explicit warnings when schema_version has drifted since stored trace.
        """
        trace = self.normalize(session_id, execution_id, provider_raw_id, raw_record)
        if trace.schema_version != original_schema_version:
            trace.normalization_warnings.append(
                "SCHEMA_VERSION_MISMATCH:"
                f"stored={original_schema_version},current={trace.schema_version}"
            )
            trace.forensic_flags.append("SCHEMA_VERSION_MISMATCH")
        return trace
