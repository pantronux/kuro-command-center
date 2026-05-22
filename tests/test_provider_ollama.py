"""Ollama provider adapter tests."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import types
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix

import main
from kuro_backend.providers.errors import ProviderUnavailableError
from kuro_backend.providers.ollama_provider import OllamaProvider
from kuro_backend.providers.registry import ProviderRegistryV2, reset_provider_registry_for_tests
from kuro_backend.providers.schemas import ProviderRequest


class _FakeHTTPResponse:
    def __init__(self, payload=None, *, lines=None):
        self.payload = json.dumps(payload or {}).encode("utf-8")
        self.lines = [
            line if isinstance(line, bytes) else json.dumps(line).encode("utf-8")
            for line in (lines or [])
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload

    def __iter__(self):
        return iter(self.lines)


@pytest.fixture(autouse=True)
def reset_registry():
    reset_provider_registry_for_tests()
    yield
    reset_provider_registry_for_tests()


@pytest.fixture()
def ollama_enabled(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_ENABLED", True, raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_BASE_URL", "http://localhost:11434", raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_OPENAI_BASE_URL", "http://localhost:11434/v1", raising=False)
    monkeypatch.setattr(main.settings, "KURO_MODEL_OLLAMA_LOCAL", "qwen", raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_DEFAULT_MODEL", "qwen", raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_USE_OPENAI_COMPAT", False, raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST", False, raising=False)
    monkeypatch.setattr(main.settings, "KURO_LOCAL_MODEL_ROUTING_ENABLED", False, raising=False)


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_ollama_disabled_by_default_does_not_contact_server(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_ENABLED", False, raising=False)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("Ollama should not be contacted while disabled")

    from kuro_backend.providers import ollama_provider

    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _fail_if_called)
    provider = OllamaProvider()

    assert provider.availability().available is False
    assert provider.availability().reason == "disabled"
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(
            ProviderRegistryV2(provider_classes={"ollama": OllamaProvider}).route_generate(
                ProviderRequest.from_prompt("hello", model_alias="ollama_local")
            )
        )


def test_missing_ollama_server_health_is_safe(monkeypatch, ollama_enabled):
    from kuro_backend.providers import ollama_provider

    def _raise_connection(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(main.settings, "KURO_OLLAMA_BASE_URL", "http://127.0.0.1:9", raising=False)
    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _raise_connection)

    health = OllamaProvider().health_check()

    assert health["status"] == "unavailable"
    assert health["reason"] == "connection_error"


def test_mocked_tags_health_ok(monkeypatch, ollama_enabled):
    from kuro_backend.providers import ollama_provider

    monkeypatch.setattr(
        ollama_provider.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse({"models": [{"name": "qwen", "model": "qwen"}]}),
    )

    health = OllamaProvider().health_check()

    assert health["status"] == "ok"
    assert health["models"] == ["qwen"]
    assert health["default_model"] == "qwen"


def test_mocked_native_generate(monkeypatch, ollama_enabled):
    from kuro_backend.providers import ollama_provider

    monkeypatch.setattr(
        ollama_provider.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            {"model": "qwen", "message": {"role": "assistant", "content": "hello"}, "done": True}
        ),
    )

    response = asyncio.run(
        OllamaProvider().generate(
            ProviderRequest.from_prompt("hello", model_alias="ollama_local"),
            model_id="qwen",
        )
    )

    assert response.provider == "ollama"
    assert response.model_id == "qwen"
    assert response.content == "hello"


def test_mocked_native_stream_maps_tokens(monkeypatch, ollama_enabled):
    from kuro_backend.providers import ollama_provider

    monkeypatch.setattr(
        ollama_provider.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            lines=[
                {"message": {"content": "he"}, "done": False},
                {"message": {"content": "llo"}, "done": False},
                {"done": True},
            ]
        ),
    )

    async def _collect():
        events = []
        async for event in OllamaProvider().stream(
            ProviderRequest.from_prompt("hello", model_alias="ollama_local"),
            model_id="qwen",
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert [event.delta for event in events if event.event_type == "token"] == ["he", "llo"]
    assert events[-1].done is True


def test_timeout_handled_safely(monkeypatch, ollama_enabled):
    from kuro_backend.providers import ollama_provider

    def _raise_timeout(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _raise_timeout)

    with pytest.raises(ProviderUnavailableError, match="provider_timeout"):
        asyncio.run(
            OllamaProvider().generate(
                ProviderRequest.from_prompt("hello", model_alias="ollama_local"),
                model_id="qwen",
            )
        )


def test_public_models_route_is_safe(monkeypatch, ollama_enabled):
    client = _auth_client(monkeypatch)

    response = client.get("/api/models")

    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body).lower()
    assert "ollama_local" in serialized
    assert "local ollama" in serialized
    assert "localhost" not in serialized
    assert "127.0.0.1" not in serialized
    assert "11434" not in serialized
    assert "qwen" not in serialized


def test_openai_compatible_generate_mapping(monkeypatch, ollama_enabled):
    from kuro_backend.providers import ollama_provider

    seen = {}

    def _fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "compat hello"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr(main.settings, "KURO_OLLAMA_USE_OPENAI_COMPAT", True, raising=False)
    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _fake_urlopen)

    response = asyncio.run(
        OllamaProvider().generate(
            ProviderRequest.from_prompt("hello", model_alias="ollama_local"),
            model_id="qwen",
        )
    )

    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["payload"]["model"] == "qwen"
    assert response.content == "compat hello"


def test_tool_like_output_remains_text(monkeypatch, ollama_enabled):
    from kuro_backend.providers import ollama_provider

    tool_like = '{"tool": "delete_file", "arguments": {"path": "/tmp/x"}}'
    monkeypatch.setattr(
        ollama_provider.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            {"model": "qwen", "message": {"role": "assistant", "content": tool_like}, "done": True}
        ),
    )

    response = asyncio.run(
        OllamaProvider().generate(
            ProviderRequest.from_prompt("emit tool json", model_alias="ollama_local"),
            model_id="qwen",
        )
    )

    assert OllamaProvider.supports_tools is False
    assert response.content == tool_like
    assert response.safety["tools_executed"] is False


def test_structured_output_invalid_json_not_trusted(monkeypatch, ollama_enabled):
    from kuro_backend.providers import ollama_provider

    monkeypatch.setattr(
        ollama_provider.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeHTTPResponse(
            {"model": "qwen", "message": {"role": "assistant", "content": "{not-json"}, "done": True}
        ),
    )

    response = asyncio.run(
        OllamaProvider().generate(
            ProviderRequest.from_prompt(
                "json please",
                model_alias="ollama_local",
                structured_output_schema={"type": "object"},
            ),
            model_id="qwen",
        )
    )

    assert response.structured is None
    assert response.finish_reason == "schema_not_guaranteed"


def test_local_routing_disabled_by_default(monkeypatch, ollama_enabled):
    monkeypatch.setenv("KURO_PROVIDER_FALLBACK_ALIASES", "ollama_local,gemini_fast")
    registry = ProviderRegistryV2()

    aliases = registry._route_aliases("gemini_fast", None)

    assert aliases == ["gemini_fast"]
