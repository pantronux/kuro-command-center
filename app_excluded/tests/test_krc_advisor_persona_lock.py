from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

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
from kuro_backend.krc_advisor import KRC_PERSONA_ID, PHD_ADVISOR_SYSTEM_PROMPT


def _client(monkeypatch):
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "Pantronux"})
    monkeypatch.setattr(
        main.auth_db,
        "get_user",
        lambda _username: {
            "display_name": "Pantronux",
            "role": "Administrator",
            "master_name": "Master Pantronux",
            "restricted_persona": "",
        },
    )
    return TestClient(main.app)


def _cookies():
    return {main.COOKIE_NAME: "Bearer dummy"}


def test_krc_persona_api_is_locked_to_advisor(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    client = _client(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        main.memory_manager,
        "set_active_persona",
        lambda persona, username="Pantronux": calls.append(persona) or {"status": "success", "persona": persona},
    )

    get_response = client.get("/api/persona", cookies=_cookies())
    post_response = client.post(
        "/api/persona",
        json={"persona": "consultant"},
        cookies=_cookies(),
    )

    assert get_response.status_code == 200
    assert get_response.json() == {
        "status": "success",
        "persona": KRC_PERSONA_ID,
        "locked": True,
        "app_profile": "krc",
        "app_role": "krc",
    }
    assert post_response.status_code == 200
    assert post_response.json()["persona"] == KRC_PERSONA_ID
    assert post_response.json()["locked"] is True
    assert calls == []


def test_legacy_persona_api_still_allows_switching(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")
    client = _client(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        main.memory_manager,
        "set_active_persona",
        lambda persona, username="Pantronux": calls.append(persona) or {"status": "success", "persona": persona},
    )

    response = client.post(
        "/api/persona",
        json={"persona": "tactical"},
        cookies=_cookies(),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success", "persona": "tactical"}
    assert calls == ["tactical"]


def test_krc_chats_query_uses_advisor_even_when_request_asks_consultant(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    client = _client(monkeypatch)
    seen: dict[str, str] = {}

    def _get_sessions(username, persona, limit=50, offset=0):
        seen["persona"] = persona
        return []

    monkeypatch.setattr(main.chat_history, "get_sessions", _get_sessions)
    monkeypatch.setattr(main.chat_history, "get_session_context", lambda _chat_id: None)

    response = client.get("/api/chats?persona=consultant", cookies=_cookies())

    assert response.status_code == 200
    assert seen["persona"] == KRC_PERSONA_ID


def test_krc_chat_endpoint_forces_advisor_persona(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    client = _client(monkeypatch)
    captured: dict[str, str] = {}

    def _resolve_runtime(**kwargs):
        captured["resolved_persona"] = kwargs["resolved_persona"]
        return (
            "legacy_chat",
            SimpleNamespace(runtime_id="sovereign", memory_namespace="kuro.sovereign"),
            False,
        )

    monkeypatch.setattr(main, "_resolve_runtime_context_for_chat_request", _resolve_runtime)
    monkeypatch.setattr(main.chat_history, "add_message", lambda *args, **kwargs: 1)
    monkeypatch.setattr(main.chat_history, "update_message_export_suggestions", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_detect_export_suggestions", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        main,
        "process_chat_with_graph",
        lambda *args, **kwargs: captured.setdefault("persona_override", kwargs["persona_override"]) and "ok",
    )

    response = client.post(
        "/api/chat",
        data={"message": "test", "persona": "consultant"},
        cookies=_cookies(),
    )

    assert response.status_code == 200
    assert captured["resolved_persona"] == KRC_PERSONA_ID
    assert captured["persona_override"] == KRC_PERSONA_ID


def test_krc_chat_stream_endpoint_forces_advisor_persona(monkeypatch):
    monkeypatch.setenv("KURO_APP_PROFILE", "krc")
    client = _client(monkeypatch)
    captured: dict[str, str] = {}

    def _resolve_runtime(**kwargs):
        captured["resolved_persona"] = kwargs["resolved_persona"]
        return (
            "legacy_stream",
            SimpleNamespace(runtime_id="sovereign", memory_namespace="kuro.sovereign"),
            False,
        )

    monkeypatch.setattr(main, "_resolve_runtime_context_for_chat_request", _resolve_runtime)
    monkeypatch.setattr(main.chat_history, "update_session_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.chat_history, "add_message", lambda *args, **kwargs: 1)
    monkeypatch.setattr(main.chat_history, "get_message_by_id", lambda _msg_id: {"timestamp": "2026-05-30T00:00:00Z"})
    monkeypatch.setattr(main.chat_history, "update_message_export_suggestions", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_detect_export_suggestions", lambda *args, **kwargs: [])

    async def _fake_stream(*args, **kwargs):
        captured["persona_override"] = kwargs["persona_override"]
        yield "stream-ok"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)

    response = client.post(
        "/api/chat/stream",
        data={"message": "test", "persona": "consultant"},
        cookies=_cookies(),
    )

    assert response.status_code == 200
    assert "stream-ok" in response.text
    assert captured["resolved_persona"] == KRC_PERSONA_ID
    assert captured["persona_override"] == KRC_PERSONA_ID


def test_phd_advisor_prompt_does_not_impersonate_real_professor():
    prompt = PHD_ADVISOR_SYSTEM_PROMPT

    assert "not a real person" in prompt
    assert "must not claim to be one" in prompt
    assert "Thomas" not in prompt
