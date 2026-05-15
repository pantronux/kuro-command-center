"""Memory V2 tests for Prompt 3."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_memory_schema_confidence_bounds():
    from kuro_backend.memory_v2.memory_store import KuroMemory

    with pytest.raises(ValidationError):
        KuroMemory(
            runtime_id="qa",
            namespace="kuro.qa",
            type="semantic",
            content="x",
            confidence=1.5,
            username="u",
        )


def test_extend_short_term_schema_idempotent(tmp_path):
    from kuro_backend.memory_v2.migrations import extend_short_term_schema

    db_path = str(tmp_path / "short_term.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE short_term (id INTEGER PRIMARY KEY, content TEXT)")
    conn.commit()
    extend_short_term_schema(conn)
    extend_short_term_schema(conn)  # must be idempotent
    cols = [r[1] for r in conn.execute("PRAGMA table_info(short_term)").fetchall()]
    assert "runtime_id" in cols
    assert "status" in cols
    assert cols.count("runtime_id") == 1
    conn.close()


def test_memory_store_retrieve_excludes_expired(tmp_path):
    from kuro_backend.memory_v2.memory_store import KuroMemory, MemoryStore

    store = MemoryStore(db_path=str(tmp_path / "mem_v2.db"))
    active = KuroMemory(
        runtime_id="qa",
        namespace="kuro.qa",
        type="semantic",
        content="active memory",
        username="u",
        expires_at="2099-01-01T00:00:00",
    )
    expired = KuroMemory(
        runtime_id="qa",
        namespace="kuro.qa",
        type="semantic",
        content="expired memory",
        username="u",
        expires_at="2000-01-01T00:00:00",
    )
    store.add(active)
    store.add(expired)
    rows = store.retrieve(
        namespace="kuro.qa",
        runtime_id="qa",
        username="u",
        limit=20,
    )
    ids = {row.id for row in rows}
    assert active.id in ids
    assert expired.id not in ids


def test_conflict_resolver_detects_high_overlap():
    from kuro_backend.memory_v2.conflict_resolver import detect_conflicts
    from kuro_backend.memory_v2.memory_store import KuroMemory

    mem1 = KuroMemory(
        runtime_id="qa",
        namespace="kuro.qa",
        type="semantic",
        content="user prefers dark mode interface",
        username="u",
    )
    mem2 = KuroMemory(
        runtime_id="qa",
        namespace="kuro.qa",
        type="semantic",
        content="user prefers dark mode interface on dashboard",
        username="u",
    )
    conflicts = detect_conflicts(mem2, [mem1])
    assert len(conflicts) == 1


def test_decay_engine_expires_stale(tmp_path):
    from kuro_backend.memory_v2.decay_engine import expire_stale_memories
    from kuro_backend.memory_v2.memory_store import KuroMemory, MemoryStore

    store = MemoryStore(db_path=str(tmp_path / "decay.db"))
    stale = KuroMemory(
        runtime_id="qa",
        namespace="kuro.qa",
        type="episodic",
        content="old memory",
        username="u",
        expires_at="2000-01-01T00:00:00",
    )
    store.add(stale)
    count = expire_stale_memories(store)
    stored = store.get_by_id(stale.id)
    assert stored is not None
    assert stored.status == "expired"
    assert count >= 1


def test_decay_engine_returns_count():
    from kuro_backend.memory_v2.decay_engine import expire_stale_memories

    mock_store = MagicMock()
    mock_store.retrieve_all_active_without_expiry.return_value = []
    mock_store.retrieve_stale.return_value = []
    count = expire_stale_memories(mock_store)
    assert count == 0
