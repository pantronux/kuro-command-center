import sys
from unittest.mock import MagicMock

# Mock all potential blockers
sys.modules["kuro_backend.observability"] = MagicMock()
sys.modules["phoenix"] = MagicMock()
sys.modules["mem0"] = MagicMock()
sys.modules["google.genai"] = MagicMock()
sys.modules["google.genai.types"] = MagicMock()
sys.modules["langgraph"] = MagicMock()
sys.modules["langgraph.graph"] = MagicMock()
sys.modules["nemoguardrails"] = MagicMock()

import pytest
from kuro_backend import chat_history

@pytest.fixture(autouse=True)
def setup_db():
    # Ensure DB is initialized
    chat_history.init_db()
    # Clear data for isolation
    conn = chat_history._get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history")
    cursor.execute("DELETE FROM chat_sessions")
    cursor.execute("DELETE FROM message_edits")
    conn.commit()
    conn.close()
    yield

def test_session_pinning():
    chat_id = "test_pin_1"
    username = "Pantronux"
    persona = "advisor"
    
    # Create session
    chat_history.create_session(chat_id, username, persona)
    chat_history.add_message("web", "user", "Hello", [], persona, None, username, chat_id)
    
    # Pin session
    success = chat_history.pin_session(chat_id)
    assert success is True
    
    session = chat_history.get_session(chat_id)
    assert session["is_pinned"] == 1
    assert session["pinned_at"] is not None
    
    # Unpin session
    success = chat_history.unpin_session(chat_id)
    assert success is True
    
    session = chat_history.get_session(chat_id)
    assert session["is_pinned"] == 0

def test_message_editing_and_truncation():
    chat_id = "test_edit_1"
    username = "Pantronux"
    persona = "advisor"
    
    # Create session and sequence of messages
    chat_history.create_session(chat_id, username, persona)
    chat_history.add_message("web", "user", "Msg 1", [], persona, None, username, chat_id) 
    chat_history.add_message("web", "assistant", "Resp 1", [], persona, None, username, chat_id) 
    chat_history.add_message("web", "user", "Msg 2", [], persona, None, username, chat_id) 
    chat_history.add_message("web", "assistant", "Resp 2", [], persona, None, username, chat_id) 
    
    history = chat_history.get_history(platform="web", chat_id=chat_id)
    assert len(history) == 4
    
    # history is reversed by get_history (DESC)
    # history[0] = Resp 2, history[1] = Msg 2, history[2] = Resp 1, history[3] = Msg 1
    msg_2_id = history[1]["id"]
    
    # Edit Msg 2
    success = chat_history.update_message_content(msg_2_id, "Msg 2 Edited")
    assert success is True
    
    # Truncate after Msg 2
    deleted_count = chat_history.delete_messages_after(msg_2_id, chat_id)
    assert deleted_count == 1 # Only Resp 2 deleted
    
    new_history = chat_history.get_history(platform="web", chat_id=chat_id)
    assert len(new_history) == 3
    # new_history[0] = Msg 2 Edited, new_history[1] = Resp 1, new_history[2] = Msg 1
    assert new_history[0]["content"] == "Msg 2 Edited"
    assert new_history[0]["is_edited"] == 1

def test_session_search():
    chat_id = "test_search_1"
    username = "Pantronux"
    persona = "advisor"
    
    chat_history.create_session(chat_id, username, persona)
    chat_history.add_message("web", "user", "The secret word is banana", [], persona, None, username, chat_id)
    chat_history.add_message("web", "assistant", "I will remember banana", [], persona, None, username, chat_id)
    chat_history.add_message("web", "user", "What is the secret?", [], persona, None, username, chat_id)
    
    results = chat_history.search_messages_in_session(chat_id, "banana")
    assert len(results) == 2
    assert "banana" in results[0]["content"].lower()

def test_bookmark_toggle():
    chat_id = "test_bookmark_1"
    username = "Pantronux"
    persona = "advisor"
    
    chat_history.create_session(chat_id, username, persona)
    chat_history.add_message("web", "assistant", "Important response", [], persona, None, username, chat_id)
    history = chat_history.get_history(platform="web", chat_id=chat_id)
    msg_id = history[0]["id"]
    
    # Bookmark
    new_state = chat_history.toggle_bookmark(msg_id)
    assert new_state == 1
    
    # Unbookmark
    new_state = chat_history.toggle_bookmark(msg_id)
    assert new_state == 0
