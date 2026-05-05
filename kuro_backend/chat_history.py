"""
Kuro AI V6.0 Sovereign - Chat History [2026-04-17]
================================================================================
Chat History Database - SQLite-based persistent storage.
Supports cross-platform sync between Telegram and Web.

PHASE 4 Fixes [2026-04-05]:
- Database safety: try-except-finally with conn.close()

--- Header Doc ---
Purpose: Cross-channel chat history persistence (Web + Telegram) in SQLite.
Caller: core.py, langgraph_core, main.py, telegram handler, memory_coordinator.
Dependencies: sqlite3, kuro_backend.config, memory_manager (for turn metadata).
Main Functions: save_interaction(), get_history(), clear_history(), get_history_for_persona().
Side Effects: Writes to kuro_chat_history.db (WAL); short-lived connections closed in finally.
"""
import sqlite3
import json
import logging
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional
from kuro_backend.config import settings
from kuro_backend import memory_manager

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

_SCHEMA_READY_FOR: Optional[str] = None
_SCHEMA_LOCK = threading.Lock()

def _reset_schema_ready_for_tests():
    global _SCHEMA_READY_FOR
    with _SCHEMA_LOCK:
        _SCHEMA_READY_FOR = None

DB_PATH = os.path.join(settings.WORKING_DIR, "kuro_chat_history.db")

def _get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
    return conn

def init_db():
    """Initialize the database schema."""
    global _SCHEMA_READY_FOR
    current_path = DB_PATH
    if _SCHEMA_READY_FOR == current_path:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY_FOR == current_path:
            return
        _init_db_locked()
        _SCHEMA_READY_FOR = current_path

def _init_db_locked():
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL DEFAULT 'web',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                attachments TEXT DEFAULT '[]',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("PRAGMA table_info(chat_history)")
        columns = {row[1] for row in cursor.fetchall()}
        if "persona" not in columns:
            cursor.execute(
                "ALTER TABLE chat_history ADD COLUMN persona TEXT NOT NULL DEFAULT 'consultant'"
            )
            logger.info("chat_history migration: added persona column with consultant default")
        if "request_id" not in columns:
            cursor.execute(
                "ALTER TABLE chat_history ADD COLUMN request_id TEXT"
            )
            logger.info("chat_history migration: added request_id column")
        if "username" not in columns:
            cursor.execute(
                "ALTER TABLE chat_history ADD COLUMN username TEXT NOT NULL DEFAULT 'Pantronux'"
            )
            logger.info("chat_history migration: added username column with Pantronux default")
        
        # uploaded_file_integrity migration
        cursor.execute("PRAGMA table_info(uploaded_file_integrity)")
        upload_cols = {row[1] for row in cursor.fetchall()}
        if "username" not in upload_cols:
            cursor.execute("ALTER TABLE uploaded_file_integrity ADD COLUMN username TEXT NOT NULL DEFAULT 'Pantronux'")
            logger.info("uploaded_file_integrity migration: added username column")
        if "expires_at" not in upload_cols:
            cursor.execute("ALTER TABLE uploaded_file_integrity ADD COLUMN expires_at DATETIME")
            logger.info("uploaded_file_integrity migration: added expires_at column")
        if "archived_at" not in upload_cols:
            cursor.execute("ALTER TABLE uploaded_file_integrity ADD COLUMN archived_at DATETIME")
            logger.info("uploaded_file_integrity migration: added archived_at column")
        if "archive_path" not in upload_cols:
            cursor.execute("ALTER TABLE uploaded_file_integrity ADD COLUMN archive_path TEXT")
            logger.info("uploaded_file_integrity migration: added archive_path column")

        cursor.execute(
            "UPDATE chat_history SET persona = 'consultant' WHERE persona IS NULL OR TRIM(persona) = ''"
        )
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON chat_history(timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_platform_persona_timestamp
            ON chat_history(platform, persona, timestamp DESC)
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_role_request_id
            ON chat_history(platform, role, request_id)
            WHERE request_id IS NOT NULL
        """)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_file_integrity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT,
                platform TEXT NOT NULL DEFAULT 'web',
                persona TEXT NOT NULL DEFAULT 'consultant',
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                expires_at DATETIME,
                archived_at DATETIME,
                archive_path TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_uploaded_integrity_stored_filename
            ON uploaded_file_integrity(stored_filename)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_uploaded_integrity_sha256
            ON uploaded_file_integrity(sha256)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_uploaded_integrity_request_id
            ON uploaded_file_integrity(request_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_uploaded_username
            ON uploaded_file_integrity(username)
            """
        )
        # chat_sessions table for multi-session support
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                chat_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                persona TEXT NOT NULL,
                title TEXT DEFAULT 'New Chat',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_persona ON chat_sessions(username, persona)")

        # Migration: Add chat_id to chat_history
        cursor.execute("PRAGMA table_info(chat_history)")
        columns = {row[1] for row in cursor.fetchall()}
        if "chat_id" not in columns:
            cursor.execute("ALTER TABLE chat_history ADD COLUMN chat_id TEXT")
            logger.info("chat_history migration: added chat_id column")
            # Populate legacy chats with a default ID based on user_persona
            cursor.execute("UPDATE chat_history SET chat_id = 'legacy_' || username || '_' || persona WHERE chat_id IS NULL")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_chat_id ON chat_history(chat_id)")

        conn.commit()
        logger.info(f"Chat history database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize chat history DB: {e}")
    finally:
        if conn:
            conn.close()

def add_message(
    platform: str,
    role: str,
    content: str,
    attachments: List[str] = None,
    persona: Optional[str] = None,
    request_id: Optional[str] = None,
    username: str = "Pantronux",
    chat_id: Optional[str] = None,
):
    """Add a message to the chat history."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        normalized_persona = memory_manager.normalize_persona(persona)
        
        # If no chat_id provided, fallback to legacy format
        final_chat_id = chat_id or f"legacy_{username}_{normalized_persona}"
        
        cursor.execute(
            "INSERT OR IGNORE INTO chat_history (platform, role, content, attachments, persona, request_id, username, chat_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (platform, role, content, json.dumps(attachments or []), normalized_persona, request_id, username, final_chat_id)
        )
        
        # Update session timestamp
        cursor.execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (final_chat_id,)
        )
        
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to add chat message: {e}")
    finally:
        if conn:
            conn.close()

def get_history(
    limit: int = 50,
    offset: int = 0,
    platform: str = None,
    persona: Optional[str] = None,
    username: str = "Pantronux",
    chat_id: Optional[str] = None,
) -> List[Dict]:
    """Get recent chat history with pagination and optional filters."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        normalized_persona = memory_manager.normalize_persona(persona)
        
        query = "SELECT * FROM chat_history WHERE username = ?"
        params = [username]
        
        if chat_id:
            query += " AND chat_id = ?"
            params.append(chat_id)
        elif persona:
            query += " AND persona = ?"
            params.append(normalized_persona)
            
        if platform:
            query += " AND platform = ?"
            params.append(platform)
            
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        history = []
        for row in rows:
            # Bug 1 Fix: Safe JSON parsing for multimodal and attachments
            raw_att = row["attachments"]
            try:
                attachments = json.loads(raw_att) if raw_att else []
            except:
                attachments = []
                
            raw_content = row["content"]
            # If content is stored as JSON (multimodal), we keep it as is for frontend processing
            # otherwise it's a raw string.
            processed_content = raw_content
            try:
                if raw_content.startswith("[") or raw_content.startswith("{"):
                    processed_content = json.loads(raw_content)
            except:
                pass

            history.append({
                "id": row["id"],
                "chat_id": row["chat_id"],
                "platform": row["platform"],
                "persona": row["persona"],
                "role": row["role"],
                "content": processed_content,
                "attachments": attachments,
                "timestamp": row["timestamp"]
            })
        
        return list(reversed(history))
    except Exception as e:
        logger.error(f"Failed to get chat history: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_total_count(platform: str = None, persona: Optional[str] = None, username: str = "Pantronux") -> int:
    """Get total count of messages for pagination."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        normalized_persona = memory_manager.normalize_persona(persona)
        if platform:
            cursor.execute(
                "SELECT COUNT(*) FROM chat_history WHERE platform = ? AND persona = ? AND username = ?",
                (platform, normalized_persona, username),
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM chat_history WHERE persona = ? AND username = ?", (normalized_persona, username))
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Failed to get chat history count: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def clear_history(platform: str = None, username: str = "Pantronux", persona: str = None):
    """Clear chat history for a specific user and optionally a specific platform or persona."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        
        query = "DELETE FROM chat_history WHERE username = ?"
        params = [username]
        
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        
        if persona:
            query += " AND persona = ?"
            params.append(persona)
            
        cursor.execute(query, tuple(params))
        conn.commit()
        logger.info(f"Chat history cleared for {username} (platform: {platform or 'all'}, persona: {persona or 'all'})")
    except Exception as e:
        logger.error(f"Failed to clear chat history: {e}")
    finally:
        if conn:
            conn.close()


def record_uploaded_file_integrity(
    request_id: Optional[str],
    platform: str,
    persona: Optional[str],
    original_filename: str,
    stored_filename: str,
    stored_path: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    username: str = "Pantronux",
) -> None:
    """Persist immutable upload integrity metadata for chain-of-custody checks."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        normalized_persona = memory_manager.normalize_persona(persona)
        
        # Expiry is 180 days from now
        from datetime import timedelta
        expires_at = (datetime.now() + timedelta(days=180)).isoformat()

        cursor.execute(
            """
            INSERT INTO uploaded_file_integrity (
                request_id, platform, persona, original_filename, stored_filename,
                stored_path, content_type, size_bytes, sha256, username, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                platform or "web",
                normalized_persona,
                original_filename,
                stored_filename,
                stored_path,
                content_type or "",
                int(size_bytes or 0),
                sha256,
                username,
                expires_at
            ),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to record upload integrity metadata: %s", e)
    finally:
        if conn:
            conn.close()


def get_uploaded_file_integrity(
    stored_filename: Optional[str] = None,
    sha256: Optional[str] = None,
    request_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Query upload integrity records for verification workflows."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        filters = []
        params: List[object] = []
        if stored_filename:
            filters.append("stored_filename = ?")
            params.append(stored_filename)
        if sha256:
            filters.append("sha256 = ?")
            params.append(sha256)
        if request_id:
            filters.append("request_id = ?")
            params.append(request_id)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)
        cursor.execute(
            f"""
            SELECT * FROM uploaded_file_integrity
            {where_clause}
            ORDER BY uploaded_at DESC
            LIMIT ?
            """,
            params,
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Failed to query upload integrity metadata: %s", e)
        return []
def search_history(query: str, username: str = "Pantronux", persona: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """Search chat history for a specific keyword."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        
        sql = "SELECT id, role, content, timestamp, persona FROM chat_history WHERE username = ? AND content LIKE ?"
        params = [username, f"%{query}%"]
        
        if persona:
            sql += " AND persona = ?"
            params.append(persona)
            
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to search chat history: {e}")
        return []
    finally:
        if conn:
            conn.close()


def list_user_files(username: str) -> List[Dict]:
    """Get active (non-archived) files for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM uploaded_file_integrity WHERE username = ? AND archived_at IS NULL ORDER BY uploaded_at DESC",
            (username,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to list user files: {e}")
        return []
    finally:
        if conn:
            conn.close()


def get_expiring_files(days_ahead: int = 0) -> List[Dict]:
    """Get files that are expiring (expires_at <= now + days_ahead)."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        from datetime import timedelta
        cutoff = (datetime.now() + timedelta(days=days_ahead)).isoformat()
        cursor.execute(
            "SELECT * FROM uploaded_file_integrity WHERE expires_at <= ? AND archived_at IS NULL",
            (cutoff,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to query expiring files: {e}")
        return []
    finally:
        if conn:
            conn.close()


def mark_file_archived(stored_filename: str, archive_path: str) -> bool:
    """Mark a file as archived in the DB."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE uploaded_file_integrity SET archived_at = CURRENT_TIMESTAMP, archive_path = ?, stored_path = NULL WHERE stored_filename = ?",
            (archive_path, stored_filename)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to mark file archived: {e}")
        return False
    finally:
        if conn:
            conn.close()

def create_session(chat_id: str, username: str, persona: str, title: str = "New Chat") -> bool:
    """Create a new chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_sessions (chat_id, username, persona, title) VALUES (?, ?, ?, ?)",
            (chat_id, username, persona, title)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to create chat session: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_sessions(username: str, persona: str) -> List[Dict]:
    """Get all chat sessions for a user and persona."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM chat_sessions WHERE username = ? AND persona = ? ORDER BY updated_at DESC",
            (username, persona)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get chat sessions: {e}")
        return []
    finally:
        if conn:
            conn.close()

def update_session_title(chat_id: str, title: str) -> bool:
    """Update the title of a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (title, chat_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to update chat session title: {e}")
        return False
    finally:
        if conn:
            conn.close()

def delete_session(chat_id: str) -> bool:
    """Delete a chat session and its history."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        # Delete history first
        cursor.execute("DELETE FROM chat_history WHERE chat_id = ?", (chat_id,))
        # Delete session
        cursor.execute("DELETE FROM chat_sessions WHERE chat_id = ?", (chat_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to delete chat session: {e}")
        return False
    finally:
        if conn:
            conn.close()

def clear_all_history(username: str) -> bool:
    """Delete ALL chat history and sessions for a user. (Legacy support)"""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_history WHERE username = ?", (username,))
        cursor.execute("DELETE FROM chat_sessions WHERE username = ?", (username,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to clear all history: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Initialize on import
init_db()
