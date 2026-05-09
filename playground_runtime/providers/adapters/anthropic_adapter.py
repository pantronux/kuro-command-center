"""
Anthropic adapter.

--- Header Doc ---
Purpose: Anthropic adapter shim via OpenAI-compatible endpoint if configured.
Caller: provider registry.
Dependencies: openai_compat_adapter.
Main Functions: AnthropicAdapter.
Side Effects: Outbound HTTP calls.
"""

from playground_runtime.providers.adapters.openai_compat_adapter import OpenAICompatAdapter


class AnthropicAdapter(OpenAICompatAdapter):
    def __init__(self, api_key: str, default_model: str = "claude-3-5-sonnet-latest"):
        super().__init__(provider_id="anthropic", base_url="https://api.anthropic.com", api_key=api_key, default_model=default_model)
