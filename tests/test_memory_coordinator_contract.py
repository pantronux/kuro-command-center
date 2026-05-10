"""Memory coordinator contract tests.

--- Header Doc ---
Purpose: Lock queue/lock/dedup behavior on Mem0 write path and chat-context
         refresh audit emission contract.
Caller: pytest memory coordinator contract gate.
Dependencies: memory_coordinator, chat_history, intelligence_db.
Main Functions: test_*.
Side Effects: In-memory monkeypatch only.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

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

from kuro_backend import chat_history, intelligence_db, memory_coordinator


def test_mem0_lock_queue_dedup_contract(monkeypatch):
    username = "contract_user"
    user_lock = memory_coordinator._get_mem0_user_lock(username)

    # Ensure clean state for deterministic queue assertions.
    with memory_coordinator._MEM0_QUEUE_LOCK:
        memory_coordinator._MEM0_PENDING_QUEUE[username].clear()
        memory_coordinator._MEM0_QUEUE_DEDUP.clear()
    memory_coordinator._MEM0_FINGERPRINTS.clear()

    monkeypatch.setattr(memory_coordinator, "_mem0_should_skip_duplicate", lambda fp: False)

    acquired = user_lock.acquire(blocking=False)
    assert acquired
    try:
        memory_coordinator.execute_mem0_extract_task(
            "input-a",
            "same-content-for-dedup",
            username=username,
        )
        memory_coordinator.execute_mem0_extract_task(
            "input-b",
            "same-content-for-dedup",
            username=username,
        )

        with memory_coordinator._MEM0_QUEUE_LOCK:
            queued = list(memory_coordinator._MEM0_PENDING_QUEUE[username])
        assert len(queued) == 1
    finally:
        user_lock.release()
        with memory_coordinator._MEM0_QUEUE_LOCK:
            memory_coordinator._MEM0_PENDING_QUEUE[username].clear()
            memory_coordinator._MEM0_QUEUE_DEDUP.clear()


def test_chat_context_refresh_emits_audit_trail(monkeypatch):
    calls = []

    def _fake_count(_chat_id):
        return memory_coordinator.CHAT_CONTEXT_REFRESH_THRESHOLD * 2

    def _fake_generate(_chat_id, _persona, _username):
        return "context"

    def _fake_audit(action: str, details: str = ""):
        calls.append((action, details))

    monkeypatch.setattr(chat_history, "get_session_message_count", _fake_count)
    monkeypatch.setattr(memory_coordinator, "generate_chat_context", _fake_generate)
    monkeypatch.setattr(intelligence_db, "add_audit_trail", _fake_audit)

    memory_coordinator.maybe_trigger_chat_context(
        chat_id="contract_chat",
        persona_scope="consultant",
        username="contract_user",
    )

    assert calls
    action, details = calls[0]
    assert action == "chat_context_refresh"
    assert "chat_id=contract_chat" in details
    assert "username=contract_user" in details
    assert "message_count_at_trigger=" in details
    assert "latency_ms=" in details
