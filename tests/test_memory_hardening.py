"""Memory hardening tests for Batch-1 safeguards.

--- Header Doc ---
Purpose: Validate Mem0 concurrency dedup, kuro_memory.json recovery, and
         semantic cache atomic write+invalidation behavior.
Caller: pytest contract gate for Prompt 1 hardening.
Dependencies: memory_coordinator, perpetual_memory, semantic_cache.
Main Functions: test_*.
Side Effects: Uses tmp_path and monkeypatch; no production state mutation.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import sys
import threading
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

from kuro_backend import memory_coordinator, perpetual_memory, semantic_cache
from kuro_backend.config import settings


def test_concurrent_write_calls_same_user_do_not_duplicate_mem0_entries(monkeypatch):
    stored = []

    def _fake_extract(user_input, final_response, user_id):
        return [{"text": f"{user_input}:{final_response}", "metadata": {"uid": user_id}}]

    def _fake_store(memories, username):
        stored.append((username, tuple(m.get("text", "") for m in memories)))

    memory_coordinator._MEM0_FINGERPRINTS.clear()
    with memory_coordinator._MEM0_QUEUE_LOCK:
        memory_coordinator._MEM0_PENDING_QUEUE.clear()
        memory_coordinator._MEM0_QUEUE_DEDUP.clear()

    monkeypatch.setattr(perpetual_memory.perpetual_memory, "extract_personal_info", _fake_extract)
    monkeypatch.setattr(perpetual_memory.perpetual_memory, "store_memories", _fake_store)

    threads = [
        threading.Thread(
            target=memory_coordinator.execute_mem0_extract_task,
            args=("same input", "same response"),
            kwargs={"username": "batch1_user"},
        )
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(stored) == 1


def test_corrupt_kuro_memory_json_triggers_backup_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKING_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "KURO_BACKUP_DIR", str(tmp_path / "backups"), raising=False)

    broken_path = tmp_path / "kuro_memory.json"
    broken_path.write_text("{not-valid-json", encoding="utf-8")

    backup_dir = tmp_path / "backups" / "daily" / "2026-05-09"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "kuro_memory.json.gz"
    with gzip.open(backup_file, "wt", encoding="utf-8") as fh:
        json.dump([{"fact": "Recovered from backup"}], fh)

    schema = perpetual_memory.load_kuro_memory_schema(broken_path)
    restored = perpetual_memory._schema_to_raw(schema)

    assert restored
    assert restored[0]["fact"] == "Recovered from backup"


def test_atomic_write_and_invalidate_success_and_failure(monkeypatch):
    calls = {"store": 0, "invalidate": 0}

    def _store_ok(*args, **kwargs):
        calls["store"] += 1

    def _invalidate(*args, **kwargs):
        calls["invalidate"] += 1
        return 1

    monkeypatch.setattr(semantic_cache, "store", _store_ok)
    monkeypatch.setattr(semantic_cache, "invalidate_tag", _invalidate)

    async def _run_success():
        async with semantic_cache.atomic_write_and_invalidate(
            username="user1",
            query="q",
            persona="consultant",
            response="r",
            tags=("user1",),
        ):
            return None

    asyncio.run(_run_success())
    assert calls["store"] == 1
    assert calls["invalidate"] == 1

    def _store_fail(*args, **kwargs):
        calls["store"] += 1
        raise RuntimeError("store failed")

    monkeypatch.setattr(semantic_cache, "store", _store_fail)

    async def _run_fail():
        async with semantic_cache.atomic_write_and_invalidate(
            username="user1",
            query="q",
            persona="consultant",
            response="r",
            tags=("user1",),
        ):
            return None

    with pytest.raises(RuntimeError):
        asyncio.run(_run_fail())
    # still exactly once from the success path
    assert calls["invalidate"] == 1
