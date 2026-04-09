"""
Kuro AI V2.0 Official - Chat History [2026-04-05]
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
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON chat_history(timestamp DESC)
        """)
        conn.commit()
        logger.info(f"Chat history database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize chat history DB: {e}")
    finally:
        if conn:
            conn.close()

def add_message(platform: str, role: str, content: str, attachments: List[str] = None):
    """Add a message to the chat history."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_history (platform, role, content, attachments) VALUES (?, ?, ?, ?)",
            (platform, role, content, json.dumps(attachments or []))
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to add chat message: {e}")
    finally:
        if conn:
            conn.close()

def get_history(limit: int = 50, offset: int = 0, platform: str = None) -> List[Dict]:
    """Get recent chat history with pagination, optionally filtered by platform."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if platform:
            cursor.execute(
                "SELECT * FROM chat_history WHERE platform = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (platform, limit, offset)
            )
        else:
            cursor.execute(
                "SELECT * FROM chat_history ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset)
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

def get_total_count(platform: str = None) -> int:
    """Get total count of messages for pagination."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if platform:
            cursor.execute("SELECT COUNT(*) FROM chat_history WHERE platform = ?", (platform,))
        else:
            cursor.execute("SELECT COUNT(*) FROM chat_history")
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

# Initialize on import
init_db()
