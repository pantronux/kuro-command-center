"""Runtime registry and runtime context migration tests (V2 Prompt 1)."""

from __future__ import annotations

import os
import sys
import types
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
from kuro_backend.runtime.runtime_context import resolve_runtime_context
from kuro_backend.runtime.runtime_registry import RuntimeRegistry


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_sovereign_fallback_for_unknown_runtime():
    ctx = resolve_runtime_context("completely_unknown_xyz")
    assert ctx.runtime_id == "sovereign"


def test_none_runtime_defaults_to_sovereign_with_warning(caplog):
    with caplog.at_level("WARNING"):
        ctx = resolve_runtime_context(None)
    assert ctx.runtime_id == "sovereign"
    assert "defaulting to sovereign" in caplog.text


def test_qa_runtime_resolves_correctly():
    RuntimeRegistry.reload()
    ctx = resolve_runtime_context("qa")
    assert ctx.memory_namespace == "kuro.qa"


def test_to_state_primitives_only_strings():
    ctx = resolve_runtime_context("qa")
    prims = ctx.to_state_primitives()
    assert all(isinstance(v, str) for v in prims.values())
    assert "runtime_id" in prims
    assert "runtime_namespace" in prims
    assert "config" not in prims


def test_add_column_if_missing_idempotent(tmp_path):
    import sqlite3

    from kuro_backend.db_utils import add_column_if_missing

    db = str(tmp_path / "test.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY)")
    add_column_if_missing(conn, "test_table", "new_col", "TEXT DEFAULT NULL")
    add_column_if_missing(conn, "test_table", "new_col", "TEXT DEFAULT NULL")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(test_table)").fetchall()]
    assert cols.count("new_col") == 1


def test_migration_idempotent(tmp_path, monkeypatch):
    from kuro_backend import chat_history

    db = tmp_path / "chat_history_runtime.db"
    monkeypatch.setattr(chat_history, "DB_PATH", str(db), raising=False)
    chat_history._reset_schema_ready_for_tests()
    chat_history.init_db()
    chat_history._reset_schema_ready_for_tests()
    chat_history.init_db()

    conn = chat_history._get_connection()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()]
        assert "runtime_id" in cols
    finally:
        conn.close()


async def _fake_stream(*args, **kwargs):
    yield "hello"


def test_legacy_chat_no_runtime_id_works(monkeypatch):
    monkeypatch.setattr(main, "process_chat_with_graph_stream", _fake_stream)
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat/stream",
        data={"message": "tes runtime", "persona": "consultant"},
        headers={"X-Chat-Session": "session_runtime_legacy_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 200
    assert "event: complete" in resp.text


def test_public_runtimes_route_hides_internal_fields(monkeypatch):
    client = _auth_client(monkeypatch)
    resp = client.get("/api/runtimes")
    assert resp.status_code == 200
    for runtime in resp.json():
        assert "tools" not in runtime
        assert "prompt_stack" not in runtime
        assert "memory_namespace" not in runtime
        assert "runtime_id" in runtime
        assert "display_name" in runtime
        assert "version" in runtime
