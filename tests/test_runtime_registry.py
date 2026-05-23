"""Runtime registry and runtime context migration tests (V2 Prompt 1)."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import yaml

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
from kuro_backend.runtime.runtime_context import resolve_runtime_context
from kuro_backend.runtime.runtime_registry import RuntimeRegistry


def _auth_client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_sovereign_fallback_for_unknown_runtime():
    ctx = resolve_runtime_context("completely_unknown_xyz")
    assert ctx.runtime_id == "sovereign"


def test_none_runtime_defaults_to_sovereign_with_warning(caplog, monkeypatch):
    monkeypatch.setenv("KURO_V2_STRICT_MODE", "false")
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


async def _capture_stream_kwargs(captured: dict, *args, **kwargs):
    captured["kwargs"] = dict(kwargs)
    yield "hello"


def _capture_graph_kwargs(captured: dict, *args, **kwargs):
    captured["kwargs"] = dict(kwargs)
    return "ok"


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


def test_existing_qa_chat_without_runtime_reuses_session_runtime(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        main,
        "process_chat_with_graph_stream",
        lambda *args, **kwargs: _capture_stream_kwargs(captured, *args, **kwargs),
    )
    monkeypatch.setattr(
        chat_history,
        "get_session",
        lambda _chat_id: {"chat_id": _chat_id, "runtime_id": "qa"},
    )
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat/stream",
        data={
            "message": "follow-up qa chat",
            "persona": "consultant",
            "chat_id": "qa_chat_existing_001",
        },
        headers={"X-Chat-Session": "qa_chat_existing_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 200
    assert captured["kwargs"]["runtime_id"] == "qa"
    assert captured["kwargs"]["runtime_namespace"] == "kuro.qa"


def test_existing_qa_chat_runtime_conflict_returns_409(monkeypatch):
    monkeypatch.setattr(
        chat_history,
        "get_session",
        lambda _chat_id: {"chat_id": _chat_id, "runtime_id": "qa"},
    )
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat/stream?runtime_id=sovereign",
        data={
            "message": "follow-up qa chat",
            "persona": "consultant",
            "chat_id": "qa_chat_existing_002",
        },
        headers={"X-Chat-Session": "qa_chat_existing_002"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 409
    assert "runtime_id conflict" in resp.json().get("detail", "")


def test_runtime_id_formdata_is_honored(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        main,
        "process_chat_with_graph_stream",
        lambda *args, **kwargs: _capture_stream_kwargs(captured, *args, **kwargs),
    )
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat/stream",
        data={
            "message": "runtime via formdata",
            "persona": "consultant",
            "runtime_id": "qa",
            "chat_id": "runtime_form_001",
        },
        headers={"X-Chat-Session": "runtime_form_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 200
    assert captured["kwargs"]["runtime_id"] == "qa"


def test_query_and_form_runtime_id_mismatch_returns_400(monkeypatch):
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat/stream?runtime_id=qa",
        data={
            "message": "runtime mismatch",
            "persona": "consultant",
            "runtime_id": "sovereign",
        },
        headers={"X-Chat-Session": "runtime_mismatch_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 400
    assert "mismatch" in resp.json().get("detail", "").lower()


def test_non_stream_existing_qa_chat_runtime_conflict_returns_409(monkeypatch):
    monkeypatch.setattr(
        chat_history,
        "get_session",
        lambda _chat_id: {"chat_id": _chat_id, "runtime_id": "qa"},
    )
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat?runtime_id=sovereign",
        data={
            "message": "non-stream conflict",
            "persona": "consultant",
            "chat_id": "qa_chat_nonstream_001",
        },
        headers={"X-Chat-Session": "qa_chat_nonstream_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 409


def test_non_stream_runtime_id_formdata_is_honored(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "process_chat_with_graph", lambda *a, **kw: _capture_graph_kwargs(captured, *a, **kw))
    client = _auth_client(monkeypatch)
    resp = client.post(
        "/api/chat",
        data={
            "message": "runtime via form",
            "persona": "consultant",
            "runtime_id": "qa",
            "chat_id": "runtime_nonstream_form_001",
        },
        headers={"X-Chat-Session": "runtime_nonstream_form_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 200
    assert captured["kwargs"]["runtime_id"] == "qa"


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


def test_admin_unknown_runtime_returns_404(monkeypatch):
    client = _auth_client(monkeypatch, username="Pantronux")
    resp = client.get(
        "/api/admin/runtimes/runtime_that_does_not_exist",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    assert resp.status_code == 404


def test_runtime_version_2_schema_version_1_still_loads(tmp_path, monkeypatch):
    config_dir = tmp_path / "runtime_cfg"
    config_dir.mkdir(parents=True, exist_ok=True)
    sovereign_cfg = {
        "runtime_id": "sovereign",
        "display_name": "Sovereign",
        "version": 2,
        "schema_version": 1,
        "memory_namespace": "kuro.sovereign",
        "retrieval_scope": [],
        "prompt_stack": ["system.sovereign.base"],
        "tools": ["manage_files"],
    }
    qa_cfg = {
        "runtime_id": "qa",
        "display_name": "QA",
        "version": 2,
        "schema_version": 1,
        "memory_namespace": "kuro.qa",
        "retrieval_scope": [],
        "prompt_stack": ["system.qa.base"],
        "tools": ["generate_report_template"],
    }
    (config_dir / "sovereign.runtime.yaml").write_text(
        yaml.safe_dump(sovereign_cfg, sort_keys=False),
        encoding="utf-8",
    )
    (config_dir / "qa.runtime.yaml").write_text(
        yaml.safe_dump(qa_cfg, sort_keys=False),
        encoding="utf-8",
    )

    original_dir = RuntimeRegistry._config_dir
    RuntimeRegistry._config_dir = config_dir
    RuntimeRegistry._cache.clear()
    try:
        RuntimeRegistry.load_all()
        loaded = RuntimeRegistry.get_exact("sovereign")
        assert loaded is not None
        assert loaded.version == 2
        assert loaded.schema_version == 1
    finally:
        RuntimeRegistry._config_dir = original_dir
        RuntimeRegistry._cache.clear()


def test_missing_sovereign_runtime_config_raises_runtime_error(tmp_path):
    config_dir = tmp_path / "runtime_cfg_missing_sovereign"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "qa.runtime.yaml").write_text(
        yaml.safe_dump(
            {
                "runtime_id": "qa",
                "display_name": "QA",
                "version": 1,
                "schema_version": 1,
                "memory_namespace": "kuro.qa",
                "retrieval_scope": [],
                "prompt_stack": ["system.qa.base"],
                "tools": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    original_dir = RuntimeRegistry._config_dir
    RuntimeRegistry._config_dir = config_dir
    RuntimeRegistry._cache.clear()
    try:
        with pytest.raises(RuntimeError):
            RuntimeRegistry.load_all()
    finally:
        RuntimeRegistry._config_dir = original_dir
        RuntimeRegistry._cache.clear()
