from __future__ import annotations

import pytest


def test_semantic_cache_is_scoped_by_user_and_runtime(monkeypatch):
    from kuro_backend import semantic_cache

    monkeypatch.setattr(semantic_cache, "ENABLED", True)
    monkeypatch.setattr(
        "kuro_backend.embedding_cache.embed_query",
        lambda text: (1.0, 0.0, 0.0),
    )
    semantic_cache.clear()

    semantic_cache.store(
        "same question",
        "consultant",
        "cached answer",
        username="alice",
        runtime_id="qa",
        runtime_namespace="kuro.qa",
    )

    assert (
        semantic_cache.lookup(
            "same question",
            "consultant",
            username="bob",
            runtime_id="qa",
            runtime_namespace="kuro.qa",
        )
        is None
    )
    assert (
        semantic_cache.lookup(
            "same question",
            "consultant",
            username="alice",
            runtime_id="sovereign",
            runtime_namespace="kuro.sovereign",
        )
        is None
    )
    assert (
        semantic_cache.lookup(
            "same question",
            "consultant",
            username="alice",
            runtime_id="qa",
            runtime_namespace="kuro.qa",
        )
        == "cached answer"
    )


def test_short_term_filters_runtime_namespace_and_preserves_v2_rows(tmp_path, monkeypatch):
    from kuro_backend import memory_manager
    from kuro_backend.memory_v2.memory_store import KuroMemory, MemoryProvenance, MemoryStore

    db_path = tmp_path / "short_term.db"
    monkeypatch.setattr(memory_manager, "SHORT_TERM_DB", str(db_path), raising=False)
    memory_manager._reset_short_term_schema_ready_for_tests()
    memory_manager.init_short_term_db()

    username = "alice"
    chat_id = "chat-1"
    memory_manager.add_short_term(
        "user",
        "sovereign turn",
        persona_scope="consultant",
        username=username,
        chat_id=chat_id,
        runtime_id="sovereign",
        namespace="kuro.sovereign",
    )
    memory_manager.add_short_term(
        "user",
        "qa turn",
        persona_scope="consultant",
        username=username,
        chat_id=chat_id,
        runtime_id="qa",
        namespace="kuro.qa",
    )

    sovereign_rows = memory_manager.get_short_term(
        persona_scope="consultant",
        username=username,
        chat_id=chat_id,
        runtime_id="sovereign",
        namespace="kuro.sovereign",
    )
    assert [row["content"] for row in sovereign_rows] == ["sovereign turn"]

    store = MemoryStore(db_path=str(db_path))
    episodic = KuroMemory(
        runtime_id="qa",
        namespace="kuro.qa",
        type="episodic",
        content="qa episodic memory survives chat pruning",
        username=username,
        provenance=MemoryProvenance(session_id=chat_id),
    )
    store.add(episodic)
    for idx in range(memory_manager.SHORT_TERM_LIMIT + 2):
        memory_manager.add_short_term(
            "assistant",
            f"turn {idx}",
            persona_scope="consultant",
            username=username,
            chat_id=chat_id,
            runtime_id="sovereign",
            namespace="kuro.sovereign",
        )

    assert store.get_by_id(episodic.id) is not None


def test_memory_store_requires_username_and_marks_conflicts(tmp_path):
    from kuro_backend.memory_v2.memory_store import KuroMemory, MemoryStore

    store = MemoryStore(db_path=str(tmp_path / "memory_v2.db"))
    first = KuroMemory(
        runtime_id="qa",
        namespace="kuro.qa",
        type="semantic",
        content="user prefers dark mode interface",
        username="alice",
    )
    second = KuroMemory(
        runtime_id="qa",
        namespace="kuro.qa",
        type="semantic",
        content="user prefers dark mode interface on dashboard",
        username="alice",
    )

    store.add(first)
    store.add(second)

    assert store.get_by_id(first.id).status == "conflicted"
    with pytest.raises(ValueError):
        store.retrieve(namespace="kuro.qa", runtime_id="qa", username="")


def test_perpetual_memory_formats_string_memories():
    from kuro_backend.perpetual_memory import PerpetualMemory

    block = PerpetualMemory().format_memories_for_context(["plain memory"])
    assert "[MEMORI] plain memory" in block
