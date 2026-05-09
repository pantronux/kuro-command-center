"""
DeepSeek mapper.

--- Header Doc ---
Purpose: Normalize DeepSeek payloads with canonical contract.
Caller: normalization registry.
Dependencies: openai_mapper.
Main Functions: DeepSeekMapper.map_to_canonical().
Side Effects: None.
"""

from playground_runtime.schema.mappers.openai_mapper import OpenAIMapper


class DeepSeekMapper(OpenAIMapper):
    schema_version = "deepseek/1.0.0"
