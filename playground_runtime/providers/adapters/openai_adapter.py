"""
OpenAI adapter.

--- Header Doc ---
Purpose: OpenAI provider adapter wrapper over OpenAI-compatible implementation.
Caller: provider registry.
Dependencies: openai_compat_adapter.
Main Functions: OpenAIAdapter.
Side Effects: Outbound HTTP calls.
"""

from playground_runtime.providers.adapters.openai_compat_adapter import OpenAICompatAdapter


class OpenAIAdapter(OpenAICompatAdapter):
    def __init__(self, api_key: str, default_model: str = "gpt-4o-mini"):
        super().__init__(provider_id="openai", base_url="https://api.openai.com", api_key=api_key, default_model=default_model)
