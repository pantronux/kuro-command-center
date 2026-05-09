"""
Provider adapters package.

--- Header Doc ---
Purpose: Concrete adapters for each external provider surface.
Caller: provider router.
Dependencies: adapter implementations.
Main Functions: BaseAdapter and concrete adapters.
Side Effects: External HTTP calls when invoked.
"""

from .base_adapter import BaseAdapter, ProviderRequest, ProviderResponse
from .gemini_adapter import GeminiAdapter
from .openai_adapter import OpenAIAdapter
from .anthropic_adapter import AnthropicAdapter
from .deepseek_adapter import DeepSeekAdapter
from .ollama_adapter import OllamaAdapter
from .openai_compat_adapter import OpenAICompatAdapter

__all__ = [
    "BaseAdapter",
    "ProviderRequest",
    "ProviderResponse",
    "GeminiAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "DeepSeekAdapter",
    "OllamaAdapter",
    "OpenAICompatAdapter",
]
