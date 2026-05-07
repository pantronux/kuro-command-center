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
import threading
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kuro_intelligence.db")

_SCHEMA_READY_FOR: Optional[str] = None
_SCHEMA_LOCK = threading.Lock()

def _reset_schema_ready_for_tests() -> None:
    global _SCHEMA_READY_FOR
    with _SCHEMA_LOCK:
        _SCHEMA_READY_FOR = None


def _get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    """Initialize the intelligence briefings database schema."""
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

        # Check if the table already exists with the OLD schema (no username column)
        cursor.execute("PRAGMA table_info(intelligence_briefings)")
        cols = [row["name"] for row in cursor.fetchall()]

        if cols and "username" not in cols:
            # Safe migration: recreate table to add username column with UNIQUE(username, date)
            logger.info("[INTELLIGENCE] Running schema migration: adding username column via table recreation...")
            cursor.execute("ALTER TABLE intelligence_briefings RENAME TO intelligence_briefings_old")
            cursor.execute("""
                CREATE TABLE intelligence_briefings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL DEFAULT 'Pantronux',
                    date TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    raw_json_data TEXT DEFAULT '{}',
                    experimental_signals TEXT DEFAULT '[]',
                    stock_recommendations TEXT DEFAULT '[]',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, date)
                )
            """)
            cursor.execute("""
                INSERT INTO intelligence_briefings (username, date, summary_text, raw_json_data, experimental_signals, created_at)
                SELECT 'Pantronux', date, summary_text, raw_json_data, experimental_signals, created_at
                FROM intelligence_briefings_old
            """)
            cursor.execute("DROP TABLE intelligence_briefings_old")
            logger.info("[INTELLIGENCE] Schema migration complete.")
        else:
            # Create fresh if not yet existing
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS intelligence_briefings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL DEFAULT 'Pantronux',
                    date TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    raw_json_data TEXT DEFAULT '{}',
                    experimental_signals TEXT DEFAULT '[]',
                    stock_recommendations TEXT DEFAULT '[]',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, date)
                )
            """)
            
            # Check for stock_recommendations column if table exists
            cursor.execute("PRAGMA table_info(intelligence_briefings)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "stock_recommendations" not in cols:
                logger.info("[INTELLIGENCE] Adding stock_recommendations column...")
                cursor.execute("ALTER TABLE intelligence_briefings ADD COLUMN stock_recommendations TEXT DEFAULT '[]'")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_briefing_user_date ON intelligence_briefings(username, date DESC)
        """)

        # Autonomous Research: source provenance table (V1.0.0 Beta 4)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_sources (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                username    TEXT NOT NULL,
                chat_id     TEXT,
                query       TEXT NOT NULL,
                source_type TEXT NOT NULL CHECK(source_type IN ('scholar', 'news', 'openclaw')),
                title       TEXT,
                link        TEXT,
                snippet     TEXT,
                year        INTEGER,
                cited_by    INTEGER,
                retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_research_sources_session ON research_sources(session_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_research_sources_username ON research_sources(username, retrieved_at DESC)
        """)

        conn.commit()
        logger.info(f"Intelligence briefings database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize intelligence briefings DB: {e}")
    finally:
        if conn:
            conn.close()


def save_research_sources(session_id: str, username: str, chat_id: Optional[str], sources: List[Dict]) -> None:
    """Save auto-retrieved research sources for provenance tracking."""
    if not sources:
        return
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        data = []
        for s in sources:
            data.append((
                session_id, username, chat_id,
                s.get("query", ""), s.get("source_type", "scholar"),
                s.get("title"), s.get("link"), s.get("snippet"),
                s.get("year"), s.get("cited_by")
            ))
        cursor.executemany(
            """INSERT INTO research_sources 
               (session_id, username, chat_id, query, source_type, title, link, snippet, year, cited_by) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            data
        )
        conn.commit()
        logger.info(f"[INTELLIGENCE] {len(sources)} research sources saved for {username} in session {session_id}")
    except Exception as e:
        logger.error(f"Failed to save research sources: {e}")
    finally:
        if conn:
            conn.close()

def get_research_sources(username: str, since_hours: int = 24) -> List[Dict]:
    """Get research sources retrieved in the last N hours."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM research_sources WHERE username = ? AND retrieved_at >= datetime('now', '-' || ? || ' hours') ORDER BY retrieved_at DESC",
            (username, since_hours)
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get research sources: {e}")
        return []
    finally:
        if conn:
            conn.close()

def search_sources_by_query(username: str, query_fragment: str) -> List[Dict]:
    """Search research sources by query fragment."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM research_sources WHERE username = ? AND (query LIKE ? OR title LIKE ? OR snippet LIKE ?) ORDER BY retrieved_at DESC",
            (username, f"%{query_fragment}%", f"%{query_fragment}%", f"%{query_fragment}%")
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to search research sources: {e}")
        return []
    finally:
        if conn:
            conn.close()


def save_briefing(date: str, summary_text: str, raw_json_data: Dict, experimental_signals: List[str], stock_recommendations: List[Dict] = None, username: str = "Pantronux") -> bool:
    """Save a daily intelligence briefing for a specific user."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO intelligence_briefings 
               (username, date, summary_text, raw_json_data, experimental_signals, stock_recommendations) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username, date, summary_text, json.dumps(raw_json_data, ensure_ascii=False), json.dumps(experimental_signals), json.dumps(stock_recommendations or []))
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
                "stock_recommendations": json.loads(row["stock_recommendations"] or '[]'),
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
                "stock_recommendations": json.loads(row["stock_recommendations"] or '[]'),
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
                "stock_recommendations": json.loads(row["stock_recommendations"] or '[]'),
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
