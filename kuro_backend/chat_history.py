"""
Kuro AI V5.0 Official - Chat History [2026-04-15]
================================================================================
Chat History Database - SQLite-based persistent storage.
Supports cross-platform sync between Telegram and Web.

PHASE 4 Fixes [2026-04-05]:
- Database safety: try-except-finally with conn.close()
"""
import sqlite3
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional
from kuro_backend.config import settings
from kuro_backend import memory_manager

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

DB_PATH = os.path.join(settings.WORKING_DIR, "kuro_chat_history.db")

def _get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
    return conn

def init_db():
    """Initialize the database schema."""
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
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
):
    """Add a message to the chat history."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        normalized_persona = memory_manager.normalize_persona(persona)
        cursor.execute(
            "INSERT OR IGNORE INTO chat_history (platform, role, content, attachments, persona, request_id) VALUES (?, ?, ?, ?, ?, ?)",
            (platform, role, content, json.dumps(attachments or []), normalized_persona, request_id)
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
) -> List[Dict]:
    """Get recent chat history with pagination and optional platform/persona filters."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        normalized_persona = memory_manager.normalize_persona(persona)
        if platform:
            cursor.execute(
                "SELECT * FROM chat_history WHERE platform = ? AND persona = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (platform, normalized_persona, limit, offset)
            )
        else:
            cursor.execute(
                "SELECT * FROM chat_history WHERE persona = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (normalized_persona, limit, offset)
            )
        rows = cursor.fetchall()
        
        history = []
        for row in rows:
            raw_att = row["attachments"]
            try:
                attachments = json.loads(raw_att) if raw_att else []
                if not isinstance(attachments, list):
                    logger.warning(
                        "chat_history attachments not a list id=%s raw=%r",
                        row["id"],
                        raw_att,
                    )
                    attachments = []
            except json.JSONDecodeError:
                logger.warning(
                    "chat_history attachments JSON decode failed id=%s raw=%r",
                    row["id"],
                    raw_att,
                )
                attachments = []
            history.append({
                "id": row["id"],
                "platform": row["platform"],
                "persona": row["persona"],
                "role": row["role"],
                "content": row["content"],
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

def get_total_count(platform: str = None, persona: Optional[str] = None) -> int:
    """Get total count of messages for pagination."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        normalized_persona = memory_manager.normalize_persona(persona)
        if platform:
            cursor.execute(
                "SELECT COUNT(*) FROM chat_history WHERE platform = ? AND persona = ?",
                (platform, normalized_persona),
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM chat_history WHERE persona = ?", (normalized_persona,))
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Failed to get chat history count: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def clear_history(platform: str = None):
    """Clear chat history, optionally for a specific platform."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if platform:
            cursor.execute("DELETE FROM chat_history WHERE platform = ?", (platform,))
        else:
            cursor.execute("DELETE FROM chat_history")
        conn.commit()
        logger.info(f"Chat history cleared (platform: {platform or 'all'})")
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
) -> None:
    """Persist immutable upload integrity metadata for chain-of-custody checks."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        normalized_persona = memory_manager.normalize_persona(persona)
        cursor.execute(
            """
            INSERT INTO uploaded_file_integrity (
                request_id, platform, persona, original_filename, stored_filename,
                stored_path, content_type, size_bytes, sha256
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    finally:
        if conn:
            conn.close()

# Initialize on import
init_db()
