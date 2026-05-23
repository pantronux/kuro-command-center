"""Provider Registry V2 tests."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import AsyncIterator

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
from kuro_backend import chat_history
from kuro_backend.providers.base import BaseProvider, done_event, text_delta_event
from kuro_backend.providers.registry import ProviderRegistryV2, reset_provider_registry_for_tests
from kuro_backend.providers.schemas import ProviderRequest, ProviderResponse, ProviderStatus, ProviderStreamEvent


class _MockGeminiProvider(BaseProvider):
    provider_id = "gemini"
    display_name = "Mock Gemini"

    def availability(self) -> ProviderStatus:
        return ProviderStatus(
            provider=self.provider_id,
            display_name=self.display_name,
            available=True,
            reason="available",
            configured=True,
            dependency_available=True,
            supports_streaming=True,
        )

    async def generate(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        return ProviderResponse(
            provider=self.provider_id,
            model_id=model_id,
            content="mock gemini response",
            trace_id=request.trace_id,
        )

    async def stream(self, request: ProviderRequest, *, model_id: str) -> AsyncIterator[ProviderStreamEvent]:
        yield text_delta_event("mock ", trace_id=request.trace_id)
        yield text_delta_event("stream", trace_id=request.trace_id)
        yield done_event(trace_id=request.trace_id)


class _FailingOpenAIProvider(_MockGeminiProvider):
    provider_id = "openai"
    display_name = "Mock OpenAI"

    async def generate(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        raise RuntimeError("primary failed")

    async def stream(self, request: ProviderRequest, *, model_id: str) -> AsyncIterator[ProviderStreamEvent]:
        raise RuntimeError("primary stream failed")
        yield done_event(trace_id=request.trace_id)  # pragma: no cover


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def reset_provider_registry_singleton():
    reset_provider_registry_for_tests()
    yield
    reset_provider_registry_for_tests()


def _parse_events(payload: str) -> list[dict]:
    events: list[dict] = []
    for block in payload.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        event = {"event": "message", "data": ""}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event["event"] = line[7:].strip()
            elif line.startswith("data: "):
                event["data"] += line[6:]
        events.append(event)
    return events


def test_provider_registry_disabled_by_default(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", False, raising=False)
    registry = ProviderRegistryV2(provider_classes={"gemini": _MockGeminiProvider})

    assert registry.get_enabled_providers() == {}
    assert registry.public_models()["enabled"] is False


def test_missing_keys_do_not_break_startup(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(main.settings, "GEMINI_API_KEY", "", raising=False)
    monkeypatch.setattr(main.settings, "OPENAI_API_KEY", "", raising=False)
    monkeypatch.setattr(main.settings, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr(main.settings, "DEEPSEEK_API_KEY", "", raising=False)
    monkeypatch.setattr(main.settings, "KURO_OLLAMA_ENABLED", False, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("KURO_OLLAMA_ENABLED", raising=False)

    health = ProviderRegistryV2().health_check()

    assert health.enabled is True
    assert set(health.providers) >= {"gemini", "openai", "anthropic", "deepseek"}
    assert all(status.available is False for status in health.providers.values())


def test_missing_sdk_does_not_break_startup(monkeypatch):
    from kuro_backend.providers import base as provider_base

    monkeypatch.setattr(main.settings, "OPENAI_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(
        provider_base.importlib.util,
        "find_spec",
        lambda name: None if name == "openai" else object(),
    )

    status = ProviderRegistryV2().provider("openai").availability()

    assert status.available is False
    assert status.reason == "unavailable_dependency"


def test_model_aliases_resolve_from_env(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(main.settings, "KURO_MODEL_OPENAI_NANO", "openai-test-model", raising=False)

    alias = ProviderRegistryV2(provider_classes={"openai": _MockGeminiProvider}).resolve_model_alias("openai_nano")

    assert alias.model_id == "openai-test-model"
    assert alias.provider == "openai"


def test_public_models_route_safe(monkeypatch):
    from kuro_backend.providers import registry as registry_module

    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(registry_module, "PROVIDER_CLASSES", {"gemini": _MockGeminiProvider})
    reset_provider_registry_for_tests()
    client = _auth_client(monkeypatch)

    response = client.get("/api/models")

    assert response.status_code == 200
    serialized = response.text.lower()
    assert "gemini_fast" in serialized
    for forbidden in ["api_key", "secret", "password", "sk-test"]:
        assert forbidden not in serialized


def test_admin_provider_health_requires_admin(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)

    anonymous = TestClient(main.app)
    assert anonymous.get("/api/admin/providers/health").status_code == 401

    non_admin = _auth_client(monkeypatch, username="Faikhira")
    assert non_admin.get(
        "/api/admin/providers/health",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    ).status_code == 403

    admin = _auth_client(monkeypatch, username="Pantronux")
    assert admin.get(
        "/api/admin/providers/health",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    ).status_code == 200


def test_mocked_provider_generate_works(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    registry = ProviderRegistryV2(provider_classes={"gemini": _MockGeminiProvider})

    response = __import__("asyncio").run(
        registry.route_generate(ProviderRequest.from_prompt("hello", model_alias="gemini_fast"))
    )

    assert response.provider == "gemini"
    assert response.content == "mock gemini response"


def test_mocked_provider_stream_works(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    registry = ProviderRegistryV2(provider_classes={"gemini": _MockGeminiProvider})

    async def _collect():
        chunks: list[str] = []
        async for event in registry.route_stream(ProviderRequest.from_prompt("hello", model_alias="gemini_fast")):
            if event.delta:
                chunks.append(event.delta)
        return "".join(chunks)

    assert __import__("asyncio").run(_collect()) == "mock stream"


def test_fallback_provider_works(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    registry = ProviderRegistryV2(
        provider_classes={
            "openai": _FailingOpenAIProvider,
            "gemini": _MockGeminiProvider,
        }
    )

    response = __import__("asyncio").run(
        registry.route_generate(
            ProviderRequest.from_prompt("hello", model_alias="openai_nano"),
            fallback_aliases=["gemini_fast"],
        )
    )

    assert response.provider == "gemini"
    assert response.content == "mock gemini response"


def test_legacy_gemini_path_still_active_when_flag_false(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", False, raising=False)
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", False, raising=False)

    async def _fake_stream(*args, **kwargs):
        yield "legacy gemini path"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    response = client.post(
        "/api/chat/stream",
        data={"message": "hello", "persona": "consultant"},
        headers={"X-Chat-Session": "provider_registry_legacy_1"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    assert "legacy gemini path" in response.text
    assert "event: complete" in response.text


def test_chat_v2_uses_provider_registry_when_both_flags_enabled(monkeypatch, tmp_path):
    from kuro_backend.providers import registry as registry_module

    monkeypatch.setattr(chat_history, "DB_PATH", str(tmp_path / "providers_chat.db"))
    chat_history._reset_schema_ready_for_tests()
    chat_history.init_db()
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(main.settings, "KURO_PROVIDER_REGISTRY_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(registry_module, "PROVIDER_CLASSES", {"gemini": _MockGeminiProvider})
    reset_provider_registry_for_tests()
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/chat/v2/stream",
        data={"message": "hello", "persona": "consultant", "chat_id": "provider_registry_chat_v2"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    events = _parse_events(response.text)
    assert any("mock " in event["data"] for event in events)
    assert any("stream" in event["data"] for event in events)
