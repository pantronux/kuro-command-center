"""Chat/streaming hardening tests.

--- Header Doc ---
Purpose: Validate cursor pagination, delete cascade, and timeout guard behavior.
Caller: pytest Batch-2 hardening gate.
Dependencies: chat_history, memory_manager, langgraph_core.
Main Functions: test_*.
Side Effects: Uses isolated tmp sqlite paths.
"""
from __future__ import annotations

import sys
import threading
import time
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

from kuro_backend import chat_history, langgraph_core, memory_manager


@pytest.fixture
def isolated_chat_db(tmp_path, monkeypatch):
    chat_db = tmp_path / "chat.db"
    short_term_db = tmp_path / "short_term.db"

    monkeypatch.setattr(chat_history, "DB_PATH", str(chat_db), raising=False)
    chat_history._reset_schema_ready_for_tests()
    chat_history.init_db()

    monkeypatch.setattr(memory_manager, "SHORT_TERM_DB", str(short_term_db), raising=False)
    memory_manager._reset_short_term_schema_ready_for_tests()
    memory_manager.init_short_term_db()
    yield


def _seed_messages(chat_id: str, username: str, count: int):
    chat_history.create_session(chat_id, username, "consultant", "Test")
    for idx in range(count):
        role = "user" if idx % 2 == 0 else "assistant"
        chat_history.add_message(
            platform="web",
            role=role,
            content=f"message-{idx}",
            persona="consultant",
            username=username,
            chat_id=chat_id,
            request_id=f"r-{idx}",
        )


def test_get_history_page_has_more_when_rows_exceed_limit(isolated_chat_db):
    _seed_messages("chat_a", "u1", 8)

    page = chat_history.get_history_page("chat_a", "u1", limit=3)

    assert len(page["messages"]) == 3
    assert page["has_more"] is True
    assert page["oldest_id"] is not None
    assert [msg["content"] for msg in page["messages"]] == [
        "message-5",
        "message-6",
        "message-7",
    ]


def test_get_history_page_before_id_returns_older_only(isolated_chat_db):
    _seed_messages("chat_b", "u2", 10)

    first_page = chat_history.get_history_page("chat_b", "u2", limit=4)
    before_id = first_page["oldest_id"]
    assert before_id is not None

    second_page = chat_history.get_history_page("chat_b", "u2", limit=4, before_id=before_id)
    assert second_page["messages"]
    assert all(msg["id"] < before_id for msg in second_page["messages"])


def test_delete_session_cascades_chat_history_edits_and_short_term(isolated_chat_db):
    username = "u3"
    chat_id = "chat_cascade"
    _seed_messages(chat_id, username, 4)

    rows = chat_history.get_history(chat_id=chat_id, username=username, limit=10)
    target_msg_id = rows[-1]["id"]
    chat_history.save_message_edit(
        original_msg_id=target_msg_id,
        chat_id=chat_id,
        username=username,
        role="assistant",
        content="old",
        edit_type="regeneration",
        edit_group_id="g1",
    )
    memory_manager.add_short_term("user", "x", persona_scope="consultant", username=username, chat_id=chat_id)

    assert chat_history.delete_session(chat_id, username=username) is True

    conn = chat_history._get_connection()
    try:
        ch_count = conn.execute(
            "SELECT COUNT(*) FROM chat_history WHERE chat_id = ? AND username = ?",
            (chat_id, username),
        ).fetchone()[0]
        edit_count = conn.execute(
            "SELECT COUNT(*) FROM message_edits WHERE chat_id = ? AND username = ?",
            (chat_id, username),
        ).fetchone()[0]
    finally:
        conn.close()

    st_conn = memory_manager._get_short_term_conn()
    try:
        st_count = st_conn.execute(
            "SELECT COUNT(*) FROM short_term WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()[0]
    finally:
        st_conn.close()

    assert ch_count == 0
    assert edit_count == 0
    assert st_count == 0


def test_run_node_with_timeout_returns_node_error_quickly():
    def _slow_node(state):
        time.sleep(2.0)
        return {**state, "ok": True}

    started = time.perf_counter()
    out = langgraph_core.run_node_with_timeout(_slow_node, {"username": "u4"}, timeout_s=1)
    elapsed = time.perf_counter() - started

    assert "node_error" in out
    assert elapsed < 2.0
