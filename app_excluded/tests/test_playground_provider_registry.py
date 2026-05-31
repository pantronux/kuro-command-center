from __future__ import annotations

import importlib

import pytest

from playground_runtime.errors import ProviderExecutionError
from playground_runtime.providers.adapters.base_adapter import ProviderRequest
from playground_runtime.providers.registry import ProviderRegistry
from playground_runtime.providers.router import ProviderRouter


def _reload_config_module():
    import playground_runtime.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    return config_module


def test_provider_registry_activation_by_key_presence(monkeypatch):
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("PLAYGROUND_OPENAI_MODEL_NAME", "gpt-test")
    monkeypatch.setenv("PLAYGROUND_OLLAMA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("PLAYGROUND_OLLAMA_MODEL_NAME", "qwen3:4b")

    cfg = _reload_config_module()
    settings = cfg.PlaygroundSettings()
    registry = ProviderRegistry(settings)
    registry.load_from_env()

    active = registry.list_active()
    assert "openai" in active
    assert "ollama" in active
    ollama_adapter = registry.get("ollama")
    assert ollama_adapter.base_url == "http://localhost:11434/v1"
    assert ollama_adapter.default_model == "qwen3:4b"


def test_provider_router_comparative_requires_min_two():
    class DummySettings:
        KURO_PLAYGROUND_PROVIDER_FAILURE_THRESHOLD = 3
        KURO_PLAYGROUND_PROVIDER_HEALTH_INTERVAL_S = 30

        def provider_env_configs(self):
            return {}

    registry = ProviderRegistry(DummySettings())
    router = ProviderRouter(registry=registry, max_concurrent=2)

    with pytest.raises(ProviderExecutionError):
        router.invoke_comparative(
            ["openai"],
            ProviderRequest(prompt="hello", model=""),
        )
