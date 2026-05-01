"""
Kuro AI V6.0 Sovereign - Intelligence Briefings Database
================================================================================
SQLite storage for daily intelligence briefings from autonomous research.

--- Header Doc ---
Purpose: Persistent store for daily intel briefings + topic watchlist.
Caller: intelligence_engine (writer), memory_coordinator (reader), main.py briefing routes.
Dependencies: sqlite3.
Main Functions: init_db(), save_briefing(), list_recent_briefings(), upsert_topic(), list_topics().
Side Effects: Writes to kuro_intelligence.db (WAL); short-lived connections closed in finally.
"""
import sqlite3
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kuro_intelligence.db")

def _get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    """Initialize the intelligence briefings database schema."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intelligence_briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT 'Pantronux',
                date TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                raw_json_data TEXT DEFAULT '{}',
                experimental_signals TEXT DEFAULT '[]',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, date)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_briefing_user_date ON intelligence_briefings(username, date DESC)
        """)
        # Migration: check for username column
        cursor.execute("PRAGMA table_info(intelligence_briefings)")
        cols = [row["name"] for row in cursor.fetchall()]
        if "username" not in cols:
            # We need to drop the old UNIQUE constraint on date if it exists.
            # SQLite doesn't support ALTER TABLE DROP CONSTRAINT. 
            # But we can just add the column and use it.
            cursor.execute("ALTER TABLE intelligence_briefings ADD COLUMN username TEXT NOT NULL DEFAULT 'Pantronux'")
            logger.info("[INTELLIGENCE] Added username column to briefings table.")
        
        conn.commit()
        logger.info(f"Intelligence briefings database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize intelligence briefings DB: {e}")
    finally:
        if conn:
            conn.close()

def save_briefing(date: str, summary_text: str, raw_json_data: Dict, experimental_signals: List[str], username: str = "Pantronux") -> bool:
    """Save a daily intelligence briefing for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO intelligence_briefings 
               (username, date, summary_text, raw_json_data, experimental_signals) 
               VALUES (?, ?, ?, ?, ?)""",
            (username, date, summary_text, json.dumps(raw_json_data, ensure_ascii=False), json.dumps(experimental_signals))
        )
        conn.commit()
        logger.info(f"[INTELLIGENCE] Briefing saved for {username} on {date}")
        return True
    except Exception as e:
        logger.error(f"Failed to save briefing: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_briefings(limit: int = 20, offset: int = 0, username: str = "Pantronux") -> List[Dict]:
    """Get recent briefings for a specific user with pagination."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM intelligence_briefings WHERE username = ? ORDER BY date DESC LIMIT ? OFFSET ?",
            (username, limit, offset)
        )
        rows = cursor.fetchall()
        
        briefings = []
        for row in rows:
            briefings.append({
                "id": row["id"],
                "date": row["date"],
                "summary_text": row["summary_text"],
                "raw_json_data": json.loads(row["raw_json_data"]),
                "experimental_signals": json.loads(row["experimental_signals"]),
                "created_at": row["created_at"]
            })
        
        return briefings
    except Exception as e:
        logger.error(f"Failed to get briefings: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_briefing_by_date(date: str, username: str = "Pantronux") -> Optional[Dict]:
    """Get a specific briefing by date for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM intelligence_briefings WHERE date = ? AND username = ?", (date, username))
        row = cursor.fetchone()
        
        if row:
            return {
                "id": row["id"],
                "date": row["date"],
                "summary_text": row["summary_text"],
                "raw_json_data": json.loads(row["raw_json_data"]),
                "experimental_signals": json.loads(row["experimental_signals"]),
                "created_at": row["created_at"]
            }
        return None
    except Exception as e:
        logger.error(f"Failed to get briefing: {e}")
        return None
    finally:
        if conn:
            conn.close()

def search_briefings(query: str, username: str = "Pantronux", limit: int = 20) -> List[Dict]:
    """Search briefings by keyword for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM intelligence_briefings WHERE username = ? AND summary_text LIKE ? ORDER BY date DESC LIMIT ?",
            (username, f"%{query}%", limit)
        )
        rows = cursor.fetchall()
        
        briefings = []
        for row in rows:
            briefings.append({
                "id": row["id"],
                "date": row["date"],
                "summary_text": row["summary_text"],
                "raw_json_data": json.loads(row["raw_json_data"]),
                "experimental_signals": json.loads(row["experimental_signals"]),
                "created_at": row["created_at"]
            })
        
        return briefings
    except Exception as e:
        logger.error(f"Failed to search briefings: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_total_count(username: str = "Pantronux") -> int:
    """Get total count of briefings for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM intelligence_briefings WHERE username = ?", (username,))
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Failed to get briefing count: {e}")
        return 0
    finally:
        if conn:
            conn.close()

# Initialize on import
init_db()
