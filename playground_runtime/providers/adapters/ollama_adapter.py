"""
Ollama adapter.

--- Header Doc ---
Purpose: Local Ollama adapter wrapper using OpenAI-compatible mode.
Caller: provider registry.
Dependencies: openai_compat_adapter.
Main Functions: OllamaAdapter.
Side Effects: Outbound HTTP calls to local endpoint.
"""

from playground_runtime.providers.adapters.openai_compat_adapter import OpenAICompatAdapter


class OllamaAdapter(OpenAICompatAdapter):
    def __init__(self, base_url: str = "http://localhost:11434", default_model: str = "llama3.1:8b"):
        super().__init__(provider_id="ollama", base_url=base_url, api_key=None, default_model=default_model)
