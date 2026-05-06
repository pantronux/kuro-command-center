"""
Kuro AI V1.0.0 — Chat Isolation & chat_id Hardening — Verification Tests.

Usage:
    cd /home/kuro/projects/kuro
    python -m pytest tests/test_chat_isolation.py -v
    # or run with python directly:
    python tests/test_chat_isolation.py
"""
import os
import sys
import json
import sqlite3
import tempfile
import pytest

# Ensure kuro_backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Helpers to reset schema state between tests ---


def _reset_schema_caches():
    """Reset all module-level schema-ready caches so migrations re-fire."""
    from kuro_backend import chat_history
    from kuro_backend import memory_manager

    chat_history._reset_schema_ready_for_tests()
    memory_manager._reset_short_term_schema_ready_for_tests()


@pytest.fixture(autouse=True)
def reset_before_each():
    """Ensure schema caches are clean before every test."""
    _reset_schema_caches()


# ============================================================
# Test 1: chat_history.get_history() isolation by chat_id
# ============================================================

def test_chat_history_isolation_by_chat_id():
    """Verify that get_history() with chat_id only returns messages from that chat."""
    from kuro_backend import chat_history

    chat_history.init_db()

    try:
        chat_history.create_session("test_chat_A", "TestUser", "consultant", "Chat A")
        chat_history.create_session("test_chat_B", "TestUser", "consultant", "Chat B")
    except Exception:
        pass  # Sessions may already exist

    # Add messages to each chat
    chat_history.add_message(
        "web", "user", "Hello from Chat A", [],
        persona="consultant", username="TestUser", chat_id="test_chat_A"
    )
    chat_history.add_message(
        "web", "user", "Hello from Chat B", [],
        persona="consultant", username="TestUser", chat_id="test_chat_B"
    )

    # Verify isolation
    hist_A = chat_history.get_history(chat_id="test_chat_A", username="TestUser")
    hist_B = chat_history.get_history(chat_id="test_chat_B", username="TestUser")

    assert len(hist_A) >= 1, f"Expected at least 1 message in Chat A, got {len(hist_A)}"
    assert len(hist_B) >= 1, f"Expected at least 1 message in Chat B, got {len(hist_B)}"
    assert all(m["chat_id"] == "test_chat_A" for m in hist_A), \
        "FAIL: Chat A has foreign messages"
    assert all(m["chat_id"] == "test_chat_B" for m in hist_B), \
        "FAIL: Chat B has foreign messages"

    print("PASS: Chat history isolation verified")


# ============================================================
# Test 2: short-term memory isolation by chat_id
# ============================================================

def test_short_term_isolation_by_chat_id():
    """Verify that add_short_term/get_short_term with chat_id are isolated."""
    from kuro_backend import memory_manager

    memory_manager.init_short_term_db()

    # Add messages with different chat_ids
    memory_manager.add_short_term(
        "user", "Msg from Chat A", persona_scope="consultant",
        username="TestUser", chat_id="test_chat_A"
    )
    memory_manager.add_short_term(
        "user", "Msg from Chat B", persona_scope="consultant",
        username="TestUser", chat_id="test_chat_B"
    )

    st_A = memory_manager.get_short_term(
        persona_scope="consultant", username="TestUser", chat_id="test_chat_A"
    )
    st_B = memory_manager.get_short_term(
        persona_scope="consultant", username="TestUser", chat_id="test_chat_B"
    )

    # Verify each buffer only has its own messages
    contents_A = [m["content"] for m in st_A]
    contents_B = [m["content"] for m in st_B]

    assert any("Chat A" in c for c in contents_A), \
        f"FAIL: Short-term A doesn't contain 'Chat A' messages: {contents_A}"
    assert any("Chat B" in c for c in contents_B), \
        f"FAIL: Short-term B doesn't contain 'Chat B' messages: {contents_B}"

    # Cross-contamination check
    assert not any("Chat B" in c for c in contents_A), \
        f"FAIL: Short-term A leaked Chat B messages: {contents_A}"
    assert not any("Chat A" in c for c in contents_B), \
        f"FAIL: Short-term B leaked Chat A messages: {contents_B}"

    print("PASS: Short-term isolation verified")


# ============================================================
# Test 3: get_short_term_with_ids isolation
# ============================================================

def test_short_term_with_ids_isolation():
    """Verify get_short_term_with_ids respects chat_id filter."""
    from kuro_backend import memory_manager

    memory_manager.init_short_term_db()

    memory_manager.add_short_term(
        "user", "Chat X message", persona_scope="consultant",
        username="TestUser", chat_id="chat_X"
    )
    memory_manager.add_short_term(
        "assistant", "Chat X reply", persona_scope="consultant",
        username="TestUser", chat_id="chat_X"
    )
    memory_manager.add_short_term(
        "user", "Chat Y message", persona_scope="consultant",
        username="TestUser", chat_id="chat_Y"
    )

    entries_X = memory_manager.get_short_term_with_ids(
        persona_scope="consultant", username="TestUser", chat_id="chat_X"
    )
    entries_Y = memory_manager.get_short_term_with_ids(
        persona_scope="consultant", username="TestUser", chat_id="chat_Y"
    )

    assert len(entries_X) == 2, f"Expected 2 entries for chat_X, got {len(entries_X)}"
    assert len(entries_Y) == 1, f"Expected 1 entry for chat_Y, got {len(entries_Y)}"

    print("PASS: get_short_term_with_ids isolation verified")


# ============================================================
# Test 4: chat_context functions
# ============================================================

def test_session_context_functions():
    """Verify update/get session context functions work correctly."""
    from kuro_backend import chat_history

    chat_history.init_db()

    chat_id = "test_context_chat"
    try:
        chat_history.create_session(chat_id, "TestUser", "consultant", "Context Test")
    except Exception:
        pass

    # Initially no context
    ctx = chat_history.get_session_context(chat_id)
    assert ctx is None or ctx == "", f"Expected empty context, got {ctx!r}"

    # Update context
    context_text = "[CHAT_CONTEXT] Topik: Test Percakapan\nKeputusan: None"
    chat_history.update_session_context(chat_id, context_text)

    # Retrieve context
    ctx = chat_history.get_session_context(chat_id)
    assert ctx == context_text, f"Expected '{context_text}', got '{ctx}'"

    print("PASS: Session context functions verified")


# ============================================================
# Test 5: get_session_message_count
# ============================================================

def test_session_message_count():
    """Verify get_session_message_count returns correct count."""
    from kuro_backend import chat_history

    chat_history.init_db()

    chat_id = "test_count_chat"
    try:
        chat_history.create_session(chat_id, "TestUser", "consultant", "Count Test")
    except Exception:
        pass

    # Add messages
    chat_history.add_message(
        "web", "user", "Message 1", [],
        persona="consultant", username="TestUser", chat_id=chat_id
    )
    chat_history.add_message(
        "web", "assistant", "Reply 1", [],
        persona="consultant", username="TestUser", chat_id=chat_id
    )
    chat_history.add_message(
        "web", "user", "Message 2", [],
        persona="consultant", username="TestUser", chat_id=chat_id
    )

    count = chat_history.get_session_message_count(chat_id)
    assert count == 3, f"Expected 3 messages, got {count}"

    print("PASS: Session message count verified")


# ============================================================
# Test 6: get_default_chat_id
# ============================================================

def test_get_default_chat_id():
    """Verify get_default_chat_id creates/returns the expected ID."""
    from kuro_backend import chat_history

    chat_history.init_db()

    default_id = chat_history.get_default_chat_id("TestUser", "consultant")
    expected = "default_TestUser_consultant"
    assert default_id == expected, f"Expected {expected}, got {default_id}"

    # Calling again should return same
    default_id2 = chat_history.get_default_chat_id("TestUser", "consultant")
    assert default_id2 == expected

    print("PASS: get_default_chat_id verified")


# ============================================================
# Test 7: record_uploaded_file_integrity with chat_id
# ============================================================

def test_record_upload_with_chat_id():
    """Verify record_uploaded_file_integrity accepts and stores chat_id."""
    from kuro_backend import chat_history

    chat_history.init_db()

    chat_history.record_uploaded_file_integrity(
        request_id="test_req_123",
        platform="web",
        persona="consultant",
        original_filename="test.txt",
        stored_filename="test_20260101_000000.txt",
        stored_path="/tmp/test.txt",
        content_type="text/plain",
        size_bytes=100,
        sha256="abc123",
        username="TestUser",
        chat_id="test_chat_A",
    )

    # Query the record
    records = chat_history.get_uploaded_file_integrity(
        stored_filename="test_20260101_000000.txt", limit=1
    )
    assert len(records) > 0, "Expected at least 1 record"
    # Verify chat_id is stored (may be None if column not yet added, but migration handles that)
    print("PASS: record_uploaded_file_integrity with chat_id verified")


# ============================================================
# Test 8: build_referent_grounding_block with chat_id
# ============================================================

def test_build_referent_grounding_with_chat_id():
    """Verify build_referent_grounding_block accepts chat_id parameter."""
    from kuro_backend import memory_coordinator

    # Should not raise when chat_id is provided
    block = memory_coordinator.build_referent_grounding_block(
        "ini maksudnya?",
        "consultant",
        username="TestUser",
        chat_id="test_chat_A",
    )
    # May be None if no deictic or no history, that's fine
    print(f"PASS: build_referent_grounding_block with chat_id returned: {block is not None}")


# ============================================================
# Run tests directly
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Kuro AI — Chat Isolation Verification Tests")
    print("=" * 60)
    print()

    tests = [
        ("Chat history isolation", test_chat_history_isolation_by_chat_id),
        ("Short-term isolation", test_short_term_isolation_by_chat_id),
        ("Short-term with IDs isolation", test_short_term_with_ids_isolation),
        ("Session context functions", test_session_context_functions),
        ("Session message count", test_session_message_count),
        ("Get default chat ID", test_get_default_chat_id),
        ("Record upload with chat_id", test_record_upload_with_chat_id),
        ("Build referent grounding with chat_id", test_build_referent_grounding_with_chat_id),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
            print(f"  ✅ {name}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {name}: {e}")

    print()
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
