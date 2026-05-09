"""
DeepSeek adapter.

--- Header Doc ---
Purpose: DeepSeek provider adapter wrapper using OpenAI-compatible API style.
Caller: provider registry.
Dependencies: openai_compat_adapter.
Main Functions: DeepSeekAdapter.
Side Effects: Outbound HTTP calls.
"""

from playground_runtime.providers.adapters.openai_compat_adapter import OpenAICompatAdapter


class DeepSeekAdapter(OpenAICompatAdapter):
    def __init__(self, api_key: str, default_model: str = "deepseek-chat"):
        super().__init__(provider_id="deepseek", base_url="https://api.deepseek.com", api_key=api_key, default_model=default_model)
