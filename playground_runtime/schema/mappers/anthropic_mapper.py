"""
Anthropic mapper.

--- Header Doc ---
Purpose: Normalize Anthropic payloads with canonical contract.
Caller: normalization registry.
Dependencies: openai_mapper.
Main Functions: AnthropicMapper.map_to_canonical().
Side Effects: None.
"""

from playground_runtime.schema.mappers.openai_mapper import OpenAIMapper


class AnthropicMapper(OpenAIMapper):
    schema_version = "anthropic/1.0.0"
