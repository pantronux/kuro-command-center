"""
Chat History Database - SQLite-based persistent storage.
Supports cross-platform sync between Telegram and Web.
"""
import sqlite3
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional
from kuro_backend.config import settings

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(settings.WORKING_DIR, "kuro_chat_history.db")

def _get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database schema."""
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
    conn.close()
    logger.info(f"Chat history database initialized at {DB_PATH}")

def add_message(platform: str, role: str, content: str, attachments: List[str] = None):
    """Add a message to the chat history."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_history (platform, role, content, attachments) VALUES (?, ?, ?, ?)",
        (platform, role, content, json.dumps(attachments or []))
    )
    conn.commit()
    conn.close()

def get_history(limit: int = 50, platform: str = None) -> List[Dict]:
    """Get recent chat history, optionally filtered by platform."""
    conn = _get_connection()
    cursor = conn.cursor()
    if platform:
        cursor.execute(
            "SELECT * FROM chat_history WHERE platform = ? ORDER BY timestamp DESC LIMIT ?",
            (platform, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM chat_history ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
    rows = cursor.fetchall()
    conn.close()
    
    history = []
    for row in rows:
        history.append({
            "id": row["id"],
            "platform": row["platform"],
            "role": row["role"],
            "content": row["content"],
            "attachments": json.loads(row["attachments"]),
            "timestamp": row["timestamp"]
        })
    
    return list(reversed(history))

def clear_history(platform: str = None):
    """Clear chat history, optionally for a specific platform."""
    conn = _get_connection()
    cursor = conn.cursor()
    if platform:
        cursor.execute("DELETE FROM chat_history WHERE platform = ?", (platform,))
    else:
        cursor.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()
    logger.info(f"Chat history cleared (platform: {platform or 'all'})")

# Initialize on import
init_db()
