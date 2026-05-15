"""Provider abstraction tests for Prompt 5."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_gemini_provider_unavailable_when_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from kuro_backend.provider.gemini_provider import GeminiProvider

    assert GeminiProvider().is_available() is False


def test_provider_router_fallback_on_primary_failure():
    from kuro_backend.provider.provider_interface import ProviderRequest, ProviderResponse
    from kuro_backend.provider.provider_router import ProviderRouter
    from kuro_backend.runtime.runtime_registry import RuntimeConfig

    config = RuntimeConfig(
        runtime_id="test",
        display_name="Test",
        memory_namespace="kuro.test",
        allowed_providers=["openai", "gemini"],
        fallback_provider="gemini",
    )
    router = ProviderRouter(config)

    mock_primary = MagicMock(is_available=lambda: True)
    mock_primary.generate = AsyncMock(side_effect=RuntimeError("primary failed"))
    mock_fallback = MagicMock(is_available=lambda: True)
    mock_fallback.generate = AsyncMock(
        return_value=ProviderResponse(
            provider="gemini",
            model="test-model",
            content="fallback response",
        )
    )

    with patch.dict(
        "kuro_backend.provider.provider_router.PROVIDER_MAP",
        {"openai": lambda: mock_primary, "gemini": lambda: mock_fallback},
    ):
        response = asyncio.run(router.route(ProviderRequest(prompt="test")))

    assert response.provider == "gemini"
    assert response.content == "fallback response"


def test_provider_router_raises_when_all_fail():
    from kuro_backend.provider.provider_interface import ProviderRequest
    from kuro_backend.provider.provider_router import ProviderRouter
    from kuro_backend.runtime.runtime_registry import RuntimeConfig

    config = RuntimeConfig(
        runtime_id="test",
        display_name="T",
        memory_namespace="kuro.test",
        allowed_providers=["gemini"],
    )
    router = ProviderRouter(config)

    mock = MagicMock(is_available=lambda: True)
    mock.generate = AsyncMock(side_effect=RuntimeError("fail"))

    with patch.dict(
        "kuro_backend.provider.provider_router.PROVIDER_MAP",
        {"gemini": lambda: mock},
    ):
        with pytest.raises(RuntimeError):
            asyncio.run(router.route(ProviderRequest(prompt="test")))


def test_legacy_streaming_path_unchanged_when_flag_off(monkeypatch):
    monkeypatch.setenv("KURO_PROVIDER_ROUTER_ENABLED", "false")
    from kuro_backend.provider.provider_router import ProviderRouter

    assert ProviderRouter.is_enabled() is False

    async def _fake_stream(*args, **kwargs):
        yield "legacy stream ok"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    response = client.post(
        "/api/chat/stream",
        data={"message": "tes provider", "persona": "consultant"},
        headers={"X-Chat-Session": "provider_stream_legacy_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert response.status_code == 200
    assert "event: complete" in response.text
