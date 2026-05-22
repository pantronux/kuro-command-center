"""Memory V3 core architecture tests."""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

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
from kuro_backend.memory_v3.reader import MemoryV3Reader
from kuro_backend.memory_v3.retention import MemoryRetentionEngine
from kuro_backend.memory_v3.schemas import MemoryEvent, MemoryItem, MemoryReadRequest, MemoryWriteRequest
from kuro_backend.memory_v3.store import MemoryV3Store
from kuro_backend.memory_v3.writer import MemoryWriter


def _auth_client(monkeypatch, username: str) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def _request(content: str, **overrides) -> MemoryWriteRequest:
    payload = {
        "workspace_id": "default",
        "username": "Pantronux",
        "runtime_id": "sovereign",
        "persona_scope": "consultant",
        "chat_id": "chat-1",
        "source_type": "conversation",
        "source_id": "msg-1",
        "content": content,
    }
    payload.update(overrides)
    return MemoryWriteRequest(**payload)


def test_memory_v3_init_idempotent(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")

    store.init_db()
    store.init_db()

    tables = set(store.table_names())
    assert "memory_events" in tables
    assert "memory_items" in tables
    assert "memory_retention_policies" in tables
    assert store.count_rows("memory_retention_policies") >= 12


def test_memory_write_event_appends(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    writer = MemoryWriter(store=store)

    result = writer.write(_request("User prefers dark mode."))

    assert result.memory_id
    assert store.count_rows("memory_events") == 1
    assert store.count_rows("memory_items") == 1
    assert store.count_rows("memory_access_log") == 1


def test_memory_write_idempotency(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    writer = MemoryWriter(store=store)
    request = _request("User prefers quiet dashboards.")

    first = writer.write(request)
    second = writer.write(request)

    assert first.memory_id == second.memory_id
    assert second.idempotent is True
    assert store.count_rows("memory_events") == 1
    assert store.count_rows("memory_items") == 1


def test_memory_item_upsert(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    event = store.append_event(
        MemoryEvent(
            event_type="test",
            idempotency_key="idem-upsert",
            workspace_id="default",
            username="Pantronux",
            runtime_id="sovereign",
            persona_scope="consultant",
            chat_id="chat-1",
            source_type="test",
            source_id="src-1",
        )
    )
    item = MemoryItem(
        memory_id="mem-test",
        canonical_key="semantic:test",
        memory_type="semantic_memory",
        content="first",
        normalized_summary="first",
        workspace_id="default",
        username="Pantronux",
        runtime_id="sovereign",
        persona_scope="consultant",
        chat_id_nullable="chat-1",
        source_event_id=event.event_id,
    )

    store.upsert_memory_item(item)
    item.content = "updated"
    item.normalized_summary = "updated"
    store.upsert_memory_item(item)

    stored = store.get_memory_item("mem-test")
    assert stored is not None
    assert stored.content == "updated"
    assert store.count_rows("memory_items") == 1


def test_user_isolation(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    writer = MemoryWriter(store=store)
    reader = MemoryV3Reader(store=store)
    writer.write(_request("User likes espresso dashboards.", username="Pantronux", source_id="u1"))
    writer.write(_request("User likes tea dashboards.", username="Faikhira", source_id="u2"))

    result = reader.read(
        MemoryReadRequest(
            username="Pantronux",
            runtime_id="sovereign",
            persona_scope="consultant",
            chat_id="chat-1",
            query="dashboards",
        )
    )

    assert len(result.items) == 1
    assert result.items[0].username == "Pantronux"


def test_runtime_isolation(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    writer = MemoryWriter(store=store)
    reader = MemoryV3Reader(store=store)
    writer.write(_request("Runtime sovereign fact.", runtime_id="sovereign", source_id="r1"))
    writer.write(_request("Runtime qa fact.", runtime_id="qa", source_id="r2"))

    result = reader.read(
        MemoryReadRequest(
            username="Pantronux",
            runtime_id="qa",
            persona_scope="consultant",
            chat_id="chat-1",
            query="Runtime",
        )
    )

    assert len(result.items) == 1
    assert result.items[0].runtime_id == "qa"


def test_chat_id_isolation(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    writer = MemoryWriter(store=store)
    reader = MemoryV3Reader(store=store)
    writer.write(_request("Chat one memory.", chat_id="chat-1", source_id="c1"))
    writer.write(_request("Chat two memory.", chat_id="chat-2", source_id="c2"))

    result = reader.read(
        MemoryReadRequest(
            username="Pantronux",
            runtime_id="sovereign",
            persona_scope="consultant",
            chat_id="chat-2",
            query="Chat",
        )
    )

    assert len(result.items) == 1
    assert result.items[0].chat_id_nullable == "chat-2"


def test_conflict_detection_basic(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    writer = MemoryWriter(store=store)

    writer.write(_request("User likes dark mode.", canonical_key="pref:theme", source_id="conf-1"))
    second = writer.write(_request("User dislikes dark mode.", canonical_key="pref:theme", source_id="conf-2"))

    conflicts = store.list_conflicts()
    assert second.conflict_ids
    assert len(conflicts) == 1
    assert conflicts[0]["status"] == "open"


def test_retention_expiry(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    event = store.append_event(
        MemoryEvent(
            event_type="test",
            idempotency_key="idem-expiry",
            workspace_id="default",
            username="Pantronux",
            runtime_id="sovereign",
            persona_scope="consultant",
            chat_id="chat-1",
            source_type="test",
            source_id="src-expiry",
        )
    )
    item = MemoryItem(
        memory_id="mem-expire",
        canonical_key="ephemeral:old",
        memory_type="ephemeral_context",
        content="old temporary memory",
        normalized_summary="old temporary memory",
        workspace_id="default",
        username="Pantronux",
        runtime_id="sovereign",
        persona_scope="consultant",
        chat_id_nullable="chat-1",
        source_event_id=event.event_id,
        expires_at="2000-01-01T00:00:00Z",
    )
    store.upsert_memory_item(item)

    expired = MemoryRetentionEngine(store=store).expire_stale_memories()

    assert expired == 1
    assert store.get_memory_item("mem-expire").status == "expired"


def test_redact_memory(tmp_path):
    store = MemoryV3Store(tmp_path / "memory_v3.db")
    writer = MemoryWriter(store=store)
    result = writer.write(_request("The API key is secret.", source_id="redact-1"))

    redacted = MemoryRetentionEngine(store=store).redact_sensitive_item(
        result.memory_id,
        actor_username="Pantronux",
        target_username="Pantronux",
        reason="user request",
    )

    item = store.get_memory_item(result.memory_id)
    assert redacted is True
    assert item.status == "redacted"
    assert item.content == "[redacted]"


def test_admin_routes_require_admin(monkeypatch):
    class _FakeStore:
        def list_conflicts(self, limit=100):
            return []

        def list_access_log(self, limit=100):
            return []

    class _FakeRetention:
        def expire_stale_memories(self):
            return 0

    monkeypatch.setattr(main, "get_memory_v3_health", lambda: {"status": "ok"})
    monkeypatch.setattr(main, "MemoryV3Store", lambda: _FakeStore())
    monkeypatch.setattr(main, "MemoryRetentionEngine", lambda: _FakeRetention())

    routes = [
        ("GET", "/api/admin/memory-v3/health"),
        ("GET", "/api/admin/memory-v3/conflicts"),
        ("GET", "/api/admin/memory-v3/access-log"),
        ("POST", "/api/admin/memory-v3/expire"),
    ]
    anonymous = TestClient(main.app)
    for method, route in routes:
        response = anonymous.request(method, route)
        assert response.status_code == 401

    non_admin = _auth_client(monkeypatch, "Faikhira")
    for method, route in routes:
        response = non_admin.request(method, route, cookies={main.COOKIE_NAME: "Bearer dummy"})
        assert response.status_code == 403

    admin = _auth_client(monkeypatch, "Pantronux")
    for method, route in routes:
        response = admin.request(method, route, cookies={main.COOKIE_NAME: "Bearer dummy"})
        assert response.status_code == 200


def test_public_status_safe(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_memory_v3_public_status",
        lambda: {"enabled": False, "initialized": False, "status": "not_initialized"},
    )
    client = _auth_client(monkeypatch, "Pantronux")

    response = client.get("/api/memory-v3/status", cookies={main.COOKIE_NAME: "Bearer dummy"})

    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body, sort_keys=True).lower()
    assert body["data"]["enabled"] is False
    for forbidden in ["db_path", "sqlite", "secret", "api_key", "password", "other users"]:
        assert forbidden not in serialized


def test_memory_v3_disabled_by_default_does_not_affect_existing_chat(monkeypatch):
    monkeypatch.setattr(main.settings, "KURO_MEMORY_V3_ENABLED", False, raising=False)
    client = TestClient(main.app)

    response = client.get("/api/capabilities")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["features"]["chat"]["available"] is True
    assert data["features"]["memory"]["v2_enabled"] is False
