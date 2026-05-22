"""Chat V2 streaming, settings, history, and lineage tests."""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

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
from kuro_backend.chat_v2.history import ChatV2HistoryService
from kuro_backend.chat_v2.streaming import chat_v2_replay_buffer


def _parse_sse(payload: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for block in payload.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        event: Dict[str, Any] = {"event": "message", "id": None, "data": None}
        data_lines: List[str] = []
        for line in block.split("\n"):
            if line.startswith("id: "):
                event["id"] = int(line[4:].strip())
            elif line.startswith("event: "):
                event["event"] = line[7:].strip()
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        data = "\n".join(data_lines).strip()
        if data == "[DONE]":
            event["data"] = {"done": True}
        else:
            try:
                event["data"] = json.loads(data)
            except Exception:
                event["data"] = {"text": data}
        events.append(event)
    return events


@pytest.fixture(autouse=True)
def isolated_chat_db(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_history, "DB_PATH", str(tmp_path / "chat_v2.db"))
    chat_history._reset_schema_ready_for_tests()
    chat_history.init_db()
    chat_v2_replay_buffer.reset()
    monkeypatch.setattr(main.llm_utils, "generate_chat_title", lambda message: "New Chat")
    yield


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def _create_session(chat_id: str, username: str = "Pantronux", persona: str = "consultant") -> None:
    assert chat_history.create_session(chat_id, username, persona, "Test Chat")


def test_legacy_stream_still_works_when_flag_false(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", False, raising=False)

    async def _fake_stream(*args, **kwargs):
        yield "legacy-ok"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/chat/stream",
        data={"message": "hello", "persona": "consultant"},
        headers={"X-Chat-Session": "legacy_stream_12345"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert any(event["event"] == "chunk" for event in events)
    assert any(event["event"] == "complete" for event in events)
    assert events[-1]["data"] == {"done": True}


def test_chat_v2_stream_emits_done(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", True, raising=False)

    async def _fake_stream(*args, **kwargs):
        yield "halo "
        yield "v2"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/chat/v2/stream",
        data={"message": "hello", "persona": "consultant", "chat_id": "chat_v2_stream_1"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [event["event"] for event in events[:2]] == ["trace", "token"]
    assert events[-1]["event"] == "done"
    assert "".join(event["data"]["data"]["text"] for event in events if event["event"] == "token") == "halo v2"


def test_chat_v2_error_path_emits_error_and_done(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", True, raising=False)

    async def _fake_stream(*args, **kwargs):
        raise RuntimeError("stream exploded")
        yield ""  # pragma: no cover

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/chat/v2/stream",
        data={"message": "hello", "persona": "consultant", "chat_id": "chat_v2_error_1"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    events = _parse_sse(response.text)
    assert response.status_code == 200
    assert any(event["event"] == "error" and "stream exploded" in event["data"]["data"]["message"] for event in events)
    assert events[-1]["event"] == "done"


def test_chat_v2_last_event_id_replay(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", True, raising=False)

    async def _fake_stream(*args, **kwargs):
        yield "one"
        yield "two"

    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    first = client.post(
        "/api/chat/v2/stream",
        data={"message": "hello", "persona": "consultant", "chat_id": "chat_v2_replay_1"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    first_events = _parse_sse(first.text)
    assert first_events[-1]["event"] == "done"

    replay = client.post(
        "/api/chat/v2/stream",
        data={"message": "hello again", "persona": "consultant", "chat_id": "chat_v2_replay_1"},
        headers={"Last-Event-ID": "1"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    replay_events = _parse_sse(replay.text)

    assert [event["event"] for event in replay_events] == ["token", "token", "done"]
    assert [event["data"]["data"].get("text") for event in replay_events if event["event"] == "token"] == ["one", "two"]


def test_chat_v2_settings_persist(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", True, raising=False)
    _create_session("chat_v2_settings_1")
    client = _auth_client(monkeypatch)

    response = client.post(
        "/api/chats/chat_v2_settings_1/settings",
        json={
            "provider_alias": "gemini",
            "model_alias": "gemini_fast",
            "temperature": 0.2,
            "runtime_id": "sovereign",
            "mode": "research",
            "tools_enabled": True,
            "web_search_enabled": True,
            "memory_v3_enabled": True,
        },
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    stored = chat_history.get_session_settings("chat_v2_settings_1", "Pantronux")
    assert stored["provider_alias"] == "gemini"
    assert stored["mode"] == "research"
    assert stored["web_search_enabled"] is True


def test_chat_v2_pagination_works(monkeypatch):
    _create_session("chat_v2_page_1")
    for idx in range(5):
        chat_history.add_message("web", "user", f"message {idx}", [], "consultant", None, "Pantronux", "chat_v2_page_1")
    client = _auth_client(monkeypatch)

    response = client.get(
        "/api/chats/chat_v2_page_1/messages?limit=2",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["messages"]) == 2
    assert data["has_more"] is True
    assert data["oldest_id"] is not None


def test_chat_v2_editing_creates_version_lineage(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", True, raising=False)
    _create_session("chat_v2_edit_1")
    user_id = chat_history.add_message("web", "user", "before", [], "consultant", None, "Pantronux", "chat_v2_edit_1")
    chat_history.add_message("web", "assistant", "after", [], "consultant", None, "Pantronux", "chat_v2_edit_1")
    client = _auth_client(monkeypatch)

    response = client.post(
        f"/api/chats/chat_v2_edit_1/messages/{user_id}/edit",
        json={"new_content": "after edit"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["edit_group_id"]
    edited = chat_history.get_message_by_id(user_id)
    assert edited["is_edited"] == 1
    assert edited["edit_group_id"] == payload["edit_group_id"]
    assert edited["parent_message_id"] == user_id


def test_chat_v2_regeneration_preserves_parent_message_id(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", True, raising=False)
    _create_session("chat_v2_regen_1")
    user_id = chat_history.add_message("web", "user", "question", [], "consultant", None, "Pantronux", "chat_v2_regen_1")
    assistant_id = chat_history.add_message("web", "assistant", "answer", [], "consultant", None, "Pantronux", "chat_v2_regen_1")
    client = _auth_client(monkeypatch)

    response = client.post(
        f"/api/chats/chat_v2_regen_1/messages/{assistant_id}/regenerate",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["parent_message_id"] == user_id


def test_chat_v2_attachment_refs_do_not_leak_raw_path(tmp_path):
    _create_session("chat_v2_attachment_1")
    chat_history.add_message(
        "web",
        "user",
        "with attachment",
        ["report.pdf"],
        "consultant",
        None,
        "Pantronux",
        "chat_v2_attachment_1",
        artifact_refs=[
            {
                "type": "file",
                "original_filename": "report.pdf",
                "stored_filename": "report.pdf",
                "path": "/home/kuro/projects/kuro/uploaded_files/Pantronux/docs/report.pdf",
            }
        ],
    )

    page = ChatV2HistoryService().get_messages(
        chat_id="chat_v2_attachment_1",
        username="Pantronux",
        limit=10,
    )
    serialized = json.dumps(page.model_dump(), sort_keys=True).lower()

    assert "/home/" not in serialized
    assert "uploaded_files" not in serialized
    assert "report.pdf" in serialized


def test_chat_v2_user_cannot_access_another_users_chat(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_CHAT_V2_ENABLED", True, raising=False)
    _create_session("chat_v2_owner_1", username="Pantronux")
    client = _auth_client(monkeypatch, username="Faikhira")

    response = client.get(
        "/api/chats/chat_v2_owner_1",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )

    assert response.status_code == 404
