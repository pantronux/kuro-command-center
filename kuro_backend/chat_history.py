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
from kuro_backend.db_utils import (
    add_column_if_missing,
    db_retry,
    get_applied_version,
    get_connection,
    record_migration,
)

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
    conn = get_connection(DB_PATH)
    conn.execute("PRAGMA synchronous=NORMAL")  # Better concurrency
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
        try:
            from kuro_backend import backup_manager

            backup_manager.snapshot_pre_migration(DB_PATH, label="chat_history")
        except Exception as snap_exc:
            logger.warning("Pre-migration snapshot skipped: %s", snap_exc)
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS uploaded_file_integrity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT,
                platform TEXT,
                persona TEXT,
                original_filename TEXT,
                stored_filename TEXT,
                stored_path TEXT,
                content_type TEXT,
                size_bytes INTEGER,
                sha256 TEXT,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                username TEXT DEFAULT 'Pantronux',
                expires_at DATETIME,
                chat_id TEXT,
                archived_at DATETIME,
                archive_path TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_sessions (
                chat_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                persona TEXT NOT NULL,
                title TEXT DEFAULT 'New Chat',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                context_summary TEXT,
                context_message_count INTEGER DEFAULT 0,
                context_updated_at DATETIME
            )
        ''')

        cursor.execute("PRAGMA table_info(uploaded_file_integrity)")
        upload_cols = {row[1] for row in cursor.fetchall()}
        if "username" not in upload_cols:
            cursor.execute("ALTER TABLE uploaded_file_integrity ADD COLUMN username TEXT NOT NULL DEFAULT 'Pantronux'")
            logger.info("uploaded_file_integrity migration: added username column")
        if "expires_at" not in upload_cols:
            cursor.execute("ALTER TABLE uploaded_file_integrity ADD COLUMN expires_at DATETIME")
            logger.info("uploaded_file_integrity migration: added expires_at column")
        if "chat_id" not in upload_cols:
            cursor.execute("ALTER TABLE uploaded_file_integrity ADD COLUMN chat_id TEXT")
            logger.info("uploaded_file_integrity migration: added chat_id column")

        # chat_sessions migration
        cursor.execute("PRAGMA table_info(chat_sessions)")
        session_cols = {row[1] for row in cursor.fetchall()}
        if session_cols:
            if "context_summary" not in session_cols:
                cursor.execute("ALTER TABLE chat_sessions ADD COLUMN context_summary TEXT")
            if "context_message_count" not in session_cols:
                cursor.execute("ALTER TABLE chat_sessions ADD COLUMN context_message_count INTEGER DEFAULT 0")
            if "context_updated_at" not in session_cols:
                cursor.execute("ALTER TABLE chat_sessions ADD COLUMN context_updated_at DATETIME")
            if "is_auto_titled" not in session_cols:
                cursor.execute("ALTER TABLE chat_sessions ADD COLUMN is_auto_titled INTEGER DEFAULT 0")

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

        # Migration: Add context_summary, context_message_count, context_updated_at to chat_sessions
        cursor.execute("PRAGMA table_info(chat_sessions)")
        session_cols = {row[1] for row in cursor.fetchall()}
        if "context_summary" not in session_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN context_summary TEXT DEFAULT ''")
            logger.info("chat_sessions migration: added context_summary column")
        if "context_message_count" not in session_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN context_message_count INTEGER DEFAULT 0")
            logger.info("chat_sessions migration: added context_message_count column")
        if "context_updated_at" not in session_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN context_updated_at DATETIME")
            logger.info("chat_sessions migration: added context_updated_at column")
        if "is_auto_titled" not in session_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN is_auto_titled INTEGER DEFAULT 0")
            logger.info("chat_sessions migration: added is_auto_titled column")

        # Migration: Add chat_id to uploaded_file_integrity
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS uploaded_file_integrity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT,
                platform TEXT,
                persona TEXT,
                original_filename TEXT,
                stored_filename TEXT,
                stored_path TEXT,
                content_type TEXT,
                size_bytes INTEGER,
                sha256 TEXT,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                username TEXT DEFAULT 'Pantronux',
                expires_at DATETIME,
                chat_id TEXT,
                archived_at DATETIME,
                archive_path TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_sessions (
                chat_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                persona TEXT NOT NULL,
                title TEXT DEFAULT 'New Chat',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                context_summary TEXT,
                context_message_count INTEGER DEFAULT 0,
                context_updated_at DATETIME
            )
        ''')

        cursor.execute("PRAGMA table_info(uploaded_file_integrity)")
        upload_cols = {row[1] for row in cursor.fetchall()}
        if "chat_id" not in upload_cols:
            cursor.execute("ALTER TABLE uploaded_file_integrity ADD COLUMN chat_id TEXT")
            logger.info("uploaded_file_integrity migration: added chat_id column")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_file_chat_id ON uploaded_file_integrity(chat_id)")

        # Migration: Add chat_id to chat_history
        cursor.execute("PRAGMA table_info(chat_history)")
        columns = {row[1] for row in cursor.fetchall()}
        if "chat_id" not in columns:
            cursor.execute("ALTER TABLE chat_history ADD COLUMN chat_id TEXT")
            logger.info("chat_history migration: added chat_id column")
            # Populate legacy chats with a default ID based on user_persona
            cursor.execute("UPDATE chat_history SET chat_id = 'legacy_' || username || '_' || persona WHERE chat_id IS NULL")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_chat_id ON chat_history(chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_chat_id_username ON chat_history(chat_id, username)")

        # Migration: Create "Default Chat" for each (username, persona) that has legacy rows
        cursor.execute("""
            INSERT OR IGNORE INTO chat_sessions (chat_id, username, persona, title)
            SELECT
                'default_' || username || '_' || persona,
                username,
                persona,
                'Default Chat'
            FROM chat_history
            WHERE chat_id IS NULL OR chat_id LIKE 'legacy_%'
            GROUP BY username, persona
        """)
        cursor.execute("""
            UPDATE chat_history
            SET chat_id = 'default_' || username || '_' || persona
            WHERE chat_id IS NULL OR chat_id LIKE 'legacy_%'
        """)
        # chat_history migration: legacy rows migrated to Default Chat per (username, persona)
        logger.info("chat_history migration: legacy rows migrated to Default Chat per (username, persona)")

        # Beta 5 migrations: Sovereign Chat features
        cursor.execute("PRAGMA table_info(chat_sessions)")
        session_cols = {row[1] for row in cursor.fetchall()}
        if "is_pinned" not in session_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0")
            logger.info("chat_sessions migration: added is_pinned column")
        if "pinned_at" not in session_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN pinned_at DATETIME DEFAULT NULL")
            logger.info("chat_sessions migration: added pinned_at column")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_pinned
            ON chat_sessions(username, persona, is_pinned, updated_at DESC)
        """)

        cursor.execute("PRAGMA table_info(chat_history)")
        history_cols = {row[1] for row in cursor.fetchall()}
        for col, ddl in [
            ("is_edited",      "INTEGER NOT NULL DEFAULT 0"),
            ("is_bookmarked",  "INTEGER NOT NULL DEFAULT 0"),
            ("is_regenerated", "INTEGER NOT NULL DEFAULT 0"),
            ("edit_group_id",  "TEXT DEFAULT NULL"),
            ("export_suggestions_json", "TEXT DEFAULT NULL"),
        ]:
            if col not in history_cols:
                cursor.execute(f"ALTER TABLE chat_history ADD COLUMN {col} {ddl}")
                logger.info(f"chat_history migration: added {col} column")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_edits (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                original_msg_id INTEGER NOT NULL,
                chat_id         TEXT NOT NULL,
                username        TEXT NOT NULL,
                role            TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content         TEXT NOT NULL,
                edit_type       TEXT NOT NULL CHECK(edit_type IN ('edit', 'regeneration')),
                edited_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                edit_group_id   TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_edits_original ON message_edits(original_msg_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_edits_chat ON message_edits(chat_id, edited_at DESC)")

        # V2 runtime migration: chat_sessions.runtime_id
        add_column_if_missing(
            conn,
            "chat_sessions",
            "runtime_id",
            "TEXT DEFAULT 'sovereign'",
        )
        cursor.execute(
            "UPDATE chat_sessions SET runtime_id='sovereign' WHERE runtime_id IS NULL"
        )

        if get_applied_version(conn) < 1:
            record_migration(conn, 1, "Initial schema baseline")
        conn.commit()
        logger.info(f"Chat history database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize chat history DB: {e}")
    finally:
        if conn:
            conn.close()

@db_retry()
def add_message(
    platform: str,
    role: str,
    content: str,
    attachments: List[str] = None,
    persona: Optional[str] = None,
    request_id: Optional[str] = None,
    username: str = "Pantronux",
    chat_id: Optional[str] = None,
) -> Optional[int]:
    """Add a message to the chat history and return its row ID if inserted."""
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
        inserted_id = int(cursor.lastrowid) if cursor.lastrowid else None
        
        # Update session timestamp
        cursor.execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (final_chat_id,)
        )
        
        conn.commit()
        return inserted_id
    except Exception as e:
        logger.error(f"Failed to add chat message: {e}")
        return None
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
    before_id: Optional[int] = None,
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

        if before_id is not None:
            query += " AND id < ?"
            params.append(int(before_id))
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
        else:
            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
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
                "timestamp": row["timestamp"],
                "is_edited": row["is_edited"] if "is_edited" in row.keys() else 0,
                "is_bookmarked": row["is_bookmarked"] if "is_bookmarked" in row.keys() else 0,
                "is_regenerated": row["is_regenerated"] if "is_regenerated" in row.keys() else 0,
                "edit_group_id": row["edit_group_id"] if "edit_group_id" in row.keys() else None,
                "export_suggestions": (
                    json.loads(row["export_suggestions_json"])
                    if "export_suggestions_json" in row.keys() and row["export_suggestions_json"]
                    else []
                ),
            })
        
        # Backward compatibility:
        # - Legacy callers of get_history() expect DESC order (newest first).
        # - Cursor pagination helper get_history_page() needs ASC order when using before_id.
        if before_id is not None:
            return list(reversed(history))
        return history
    except Exception as e:
        logger.error(f"Failed to get chat history: {e}")
        return []
    finally:
        if conn:
            conn.close()


def get_history_page(
    chat_id: str,
    username: str,
    limit: int = 50,
    before_id: Optional[int] = None,
) -> Dict:
    """Return cursor-paginated history page with has_more + oldest_id."""
    page_limit = max(1, int(limit))
    rows = get_history(
        limit=page_limit + 1,
        platform=None,
        persona=None,
        username=username,
        chat_id=chat_id,
        before_id=before_id,
    )
    if before_id is None:
        rows = list(reversed(rows))
    has_more = len(rows) > page_limit
    if has_more:
        # get_history returns ascending order; drop the oldest overflow row.
        rows = rows[1:]
    oldest_id = rows[0]["id"] if rows else None
    return {
        "messages": rows,
        "has_more": bool(has_more),
        "oldest_id": oldest_id,
    }

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

@db_retry()
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


@db_retry()
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
    chat_id: Optional[str] = None,
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
                stored_path, content_type, size_bytes, sha256, username, expires_at, chat_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                expires_at,
                chat_id,
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


@db_retry()
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

@db_retry()
def create_session(
    chat_id: str,
    username: str,
    persona: str,
    title: str = "New Chat",
    runtime_id: str = "sovereign",
) -> bool:
    """Create a new chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_sessions (chat_id, username, persona, title, runtime_id) VALUES (?, ?, ?, ?, ?)",
            (chat_id, username, persona, title, runtime_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to create chat session: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_sessions(username: str, persona: str, limit: int = 50, offset: int = 0) -> List[Dict]:
    """Get all chat sessions for a user and persona."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM chat_sessions WHERE username = ? AND persona = ? ORDER BY is_pinned DESC, pinned_at DESC, updated_at DESC LIMIT ? OFFSET ?",
            (username, persona, limit, offset)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get chat sessions: {e}")
        return []
    finally:
        if conn:
            conn.close()

@db_retry()
def update_session_title(chat_id: str, title: str, is_auto_titled: Optional[bool] = None) -> bool:
    """Update the title of a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if is_auto_titled is None:
            cursor.execute(
                "UPDATE chat_sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
                (title, chat_id),
            )
        else:
            cursor.execute(
                "UPDATE chat_sessions SET title = ?, is_auto_titled = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
                (title, 1 if is_auto_titled else 0, chat_id),
            )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to update chat session title: {e}")
        return False
    finally:
        if conn:
            conn.close()

@db_retry()
def delete_session(chat_id: str, username: Optional[str] = None) -> bool:
    """Delete a chat session and its history."""
    from kuro_backend import memory_manager
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if username:
            cursor.execute(
                "DELETE FROM message_edits WHERE chat_id = ? AND username = ?",
                (chat_id, username),
            )
            cursor.execute(
                "DELETE FROM chat_history WHERE chat_id = ? AND username = ?",
                (chat_id, username),
            )
            cursor.execute(
                "DELETE FROM uploaded_file_integrity WHERE chat_id = ? AND username = ?",
                (chat_id, username),
            )
            cursor.execute(
                "DELETE FROM chat_sessions WHERE chat_id = ? AND username = ?",
                (chat_id, username),
            )
        else:
            cursor.execute("DELETE FROM message_edits WHERE chat_id = ?", (chat_id,))
            cursor.execute("DELETE FROM chat_history WHERE chat_id = ?", (chat_id,))
            cursor.execute("DELETE FROM uploaded_file_integrity WHERE chat_id = ?", (chat_id,))
            cursor.execute("DELETE FROM chat_sessions WHERE chat_id = ?", (chat_id,))

        conn.commit()

        # Cascade delete short_term buffer
        try:
            memory_manager.delete_short_term_by_chat_id(chat_id)
        except Exception as mm_err:
            logger.error(f"Failed to cascade delete short_term for {chat_id}: {mm_err}")

        return True
    except Exception as e:
        logger.error(f"Failed to delete chat session: {e}")
        return False
    finally:
        if conn:
            conn.close()

@db_retry()
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

# --- chat_context & session context management ---

@db_retry()
def update_session_context(chat_id: str, context_summary: str) -> bool:
    """Upsert the context summary for a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET context_summary = ?, context_updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (context_summary or "", chat_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to update session context: {e}")
        return False
    finally:
        if conn:
            conn.close()


def get_session_context(chat_id: str) -> Optional[str]:
    """Retrieve the context summary for a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT context_summary FROM chat_sessions WHERE chat_id = ?",
            (chat_id,)
        )
        row = cursor.fetchone()
        if row:
            return row["context_summary"] or None
        return None
    except Exception as e:
        logger.error(f"Failed to get session context: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_session_message_count(chat_id: str) -> int:
    """Count total messages (user + assistant) for a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM chat_history WHERE chat_id = ?",
            (chat_id,)
        )
        row = cursor.fetchone()
        return int(row["cnt"]) if row else 0
    except Exception as e:
        logger.error(f"Failed to get session message count: {e}")
        return 0
    finally:
        if conn:
            conn.close()


def update_session_message_count(chat_id: str, count: int) -> bool:
    """Update the message count tracker for a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET context_message_count = ? WHERE chat_id = ?",
            (int(count), chat_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to update session message count: {e}")
        return False
    finally:
        if conn:
            conn.close()


def get_default_chat_id(username: str, persona: str) -> str:
    """Get or create the 'Default Chat' for a (username, persona) pair."""
    default_id = f"default_{username}_{persona}"
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT chat_id FROM chat_sessions WHERE chat_id = ?",
            (default_id,)
        )
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO chat_sessions (chat_id, username, persona, title) VALUES (?, ?, ?, ?)",
                (default_id, username, persona, "Default Chat")
            )
            conn.commit()
        return default_id
    except Exception as e:
        logger.error(f"Failed to get default chat id: {e}")
        return default_id
    finally:
        if conn:
            conn.close()



# --- Beta 5 Sovereign Chat Features ---

def get_session(chat_id: str) -> Optional[Dict]:
    """Retrieve a single chat session by ID."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chat_sessions WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get chat session: {e}")
        return None
    finally:
        if conn:
            conn.close()

def pin_session(chat_id: str) -> bool:
    """Pin a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET is_pinned = 1, pinned_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (chat_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to pin session: {e}")
        return False
    finally:
        if conn:
            conn.close()

def unpin_session(chat_id: str) -> bool:
    """Unpin a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET is_pinned = 0, pinned_at = NULL WHERE chat_id = ?",
            (chat_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to unpin session: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_pinned_sessions(username: str, persona: str) -> List[Dict]:
    """Get only pinned sessions for a user and persona."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM chat_sessions WHERE username = ? AND persona = ? AND is_pinned = 1 ORDER BY pinned_at DESC",
            (username, persona)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get pinned sessions: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_message_by_id(message_id: int) -> Optional[Dict]:
    """Retrieve a single message by ID."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chat_history WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get message by id: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_preceding_user_message(assistant_msg_id: int, chat_id: str) -> Optional[Dict]:
    """Find the user message that immediately preceded this assistant message."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM chat_history WHERE chat_id = ? AND role = 'user' AND id < ? ORDER BY id DESC LIMIT 1",
            (chat_id, assistant_msg_id)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get preceding user message: {e}")
        return None
    finally:
        if conn:
            conn.close()

def delete_messages_after(message_id: int, chat_id: str) -> int:
    """Delete all messages after a specific message ID in a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM chat_history WHERE chat_id = ? AND id > ?",
            (chat_id, message_id)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        return deleted_count
    except Exception as e:
        logger.error(f"Failed to delete messages after {message_id}: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def update_message_content(message_id: int, new_content: str) -> bool:
    """Update a message's content and mark as edited."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_history SET content = ?, is_edited = 1 WHERE id = ?",
            (new_content, message_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to update message content: {e}")
        return False
    finally:
        if conn:
            conn.close()


def update_message_export_suggestions(message_id: int, suggestions: List[Dict]) -> bool:
    """Persist export suggestions metadata for a message."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_history SET export_suggestions_json = ? WHERE id = ?",
            (json.dumps(suggestions or [], ensure_ascii=False), message_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to update export suggestions: {e}")
        return False
    finally:
        if conn:
            conn.close()

def save_message_edit(original_msg_id: int, chat_id: str, username: str,
                      role: str, content: str, edit_type: str, edit_group_id: str) -> bool:
    """Save an original version of a message to the edits history table."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO message_edits (original_msg_id, chat_id, username, role, content, edit_type, edit_group_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (original_msg_id, chat_id, username, role, content, edit_type, edit_group_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to save message edit: {e}")
        return False
    finally:
        if conn:
            conn.close()

def toggle_bookmark(message_id: int) -> Optional[int]:
    """Toggle the bookmark state of a message."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_bookmarked FROM chat_history WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        new_state = 1 if row["is_bookmarked"] == 0 else 0
        cursor.execute("UPDATE chat_history SET is_bookmarked = ? WHERE id = ?", (new_state, message_id))
        conn.commit()
        return new_state
    except Exception as e:
        logger.error(f"Failed to toggle bookmark: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_bookmarked_messages(chat_id: str) -> List[Dict]:
    """Get all bookmarked messages for a chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM chat_history WHERE chat_id = ? AND is_bookmarked = 1 ORDER BY id ASC",
            (chat_id,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get bookmarked messages: {e}")
        return []
    finally:
        if conn:
            conn.close()

def search_messages_in_session(chat_id: str, query: str, limit: int = 20) -> List[Dict]:
    """Search for messages within a specific chat session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM chat_history WHERE chat_id = ? AND content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (chat_id, f"%{query}%", limit)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to search messages in session: {e}")
        return []
    finally:
        if conn:
            conn.close()

# Initialize on import
init_db()
