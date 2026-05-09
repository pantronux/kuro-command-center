from __future__ import annotations

import importlib


def _reload_config_module():
    import playground_runtime.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    return config_module


def test_playground_provider_env_canonical_six(monkeypatch):
    monkeypatch.setenv("PLAYGROUND_OPENAI_API_KEY", "k-openai")
    monkeypatch.setenv("PLAYGROUND_OPENAI_MODEL_NAME", "gpt-test")
    monkeypatch.setenv("PLAYGROUND_GEMINI_API_KEY", "k-gemini")
    monkeypatch.setenv("PLAYGROUND_GEMINI_MODEL_NAME", "gem-test")
    monkeypatch.setenv("PLAYGROUND_ANTHROPIC_API_KEY", "k-anth")
    monkeypatch.setenv("PLAYGROUND_DEEPSEEK_API_KEY", "k-deep")
    monkeypatch.setenv("PLAYGROUND_OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("PLAYGROUND_OPENAI_COMPAT_BASE_URL", "http://localhost:8080/v1")

    cfg = _reload_config_module()
    settings = cfg.PlaygroundSettings()
    providers = settings.provider_env_configs()

    assert set(providers.keys()) == {
        "openai",
        "gemini",
        "anthropic",
        "deepseek",
        "ollama",
        "openai_compat",
    }
    assert providers["openai"].active is True
    assert providers["ollama"].active is True
    assert providers["openai_compat"].active is True


def test_playground_flags_default_off(monkeypatch):
    keys = [
        "KURO_PLAYGROUND_ENABLED",
        "KURO_PLAYGROUND_API_ENABLED",
        "KURO_PLAYGROUND_RESEARCH_MODE",
        "KURO_PLAYGROUND_FORENSIC_MODE",
        "KURO_PLAYGROUND_COMPARATIVE_MODE",
        "KURO_PLAYGROUND_ONTOLOGY_MODE",
        "KURO_PLAYGROUND_TELEMETRY_ENABLED",
        "KURO_PLAYGROUND_HALLUCINATION_ANALYZER",
        "KURO_PLAYGROUND_EPISTEMIC_DIFF",
        "KURO_PLAYGROUND_ONTOLOGY_RECONSTRUCTION",
        "KURO_PLAYGROUND_REPORT_EXPORT",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    cfg = _reload_config_module()
    settings = cfg.PlaygroundSettings()

    assert settings.KURO_PLAYGROUND_ENABLED is False
    assert settings.KURO_PLAYGROUND_API_ENABLED is False
    assert settings.KURO_PLAYGROUND_RESEARCH_MODE is False
    assert settings.KURO_PLAYGROUND_FORENSIC_MODE is False
    assert settings.KURO_PLAYGROUND_COMPARATIVE_MODE is False
    assert settings.KURO_PLAYGROUND_ONTOLOGY_MODE is False
    assert settings.KURO_PLAYGROUND_TELEMETRY_ENABLED is False
    assert settings.KURO_PLAYGROUND_HALLUCINATION_ANALYZER is False
    assert settings.KURO_PLAYGROUND_EPISTEMIC_DIFF is False
    assert settings.KURO_PLAYGROUND_ONTOLOGY_RECONSTRUCTION is False
    assert settings.KURO_PLAYGROUND_REPORT_EXPORT is False
