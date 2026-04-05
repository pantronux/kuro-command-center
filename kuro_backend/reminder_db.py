"""
Kuro Reminder Database - SQLite-based Reminder System
======================================================
Stores and manages reminders with status tracking for notification scheduling.
"""
import sqlite3
import logging
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional
from kuro_backend.tools import PROJECT_ROOT

logger = logging.getLogger(__name__)

REMINDER_DB = os.path.join(PROJECT_ROOT, "kuro_reminders.db")
_lock = threading.Lock()


def _get_conn():
    """Get SQLite connection for reminder database."""
    conn = sqlite3.connect(REMINDER_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_reminder_db():
    """Initialize reminder database with schema."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            event_time TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            source TEXT DEFAULT 'web',
            context TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notified_10m INTEGER DEFAULT 0,
            notified_event INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Reminder database initialized.")


def add_reminder(event_name: str, event_time: str, description: str = "", 
                 source: str = "web", context: str = "") -> int:
    """
    Add a new reminder to the database.
    
    Args:
        event_name: Name of the event
        event_time: ISO format datetime string
        description: Description of the event
        source: 'web' or 'telegram'
        context: Additional context from ChromaDB lookup
    
    Returns:
        The ID of the newly created reminder
    """
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reminders (event_name, event_time, description, source, context)
        VALUES (?, ?, ?, ?, ?)
    """, (event_name, event_time, description, source, context))
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Reminder added: {event_name} at {event_time} (ID: {reminder_id})")
    return reminder_id


def get_pending_reminders() -> List[Dict]:
    """Get all reminders that are still pending (not completed)."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM reminders 
        WHERE status != 'completed' 
        ORDER BY event_time ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upcoming_reminders(limit: int = 20) -> List[Dict]:
    """Get upcoming reminders sorted by time."""
    conn = _get_conn()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        SELECT * FROM reminders 
        WHERE event_time > ? AND status != 'completed'
        ORDER BY event_time ASC
        LIMIT ?
    """, (now, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_reminder_history(limit: int = 50) -> List[Dict]:
    """Get past reminders (completed or event time passed)."""
    conn = _get_conn()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        SELECT * FROM reminders 
        WHERE event_time <= ? OR status = 'completed'
        ORDER BY event_time DESC
        LIMIT ?
    """, (now, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_reminder_by_id(reminder_id: int) -> Optional[Dict]:
    """Get a specific reminder by ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_reminder_status(reminder_id: int, status: str):
    """Update the status of a reminder."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
    conn.commit()
    conn.close()
    logger.info(f"Reminder {reminder_id} status updated to: {status}")


def mark_notified_10m(reminder_id: int):
    """Mark that the 10-minute notification has been sent."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reminders SET notified_10m = 1, status = 'notified_10m' 
        WHERE id = ?
    """, (reminder_id,))
    conn.commit()
    conn.close()
    logger.info(f"Reminder {reminder_id} marked as notified (10m)")


def mark_notified_event(reminder_id: int):
    """Mark that the event-time notification has been sent."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reminders SET notified_event = 1, status = 'notified_event' 
        WHERE id = ?
    """, (reminder_id,))
    conn.commit()
    conn.close()
    logger.info(f"Reminder {reminder_id} marked as notified (event)")


def mark_completed(reminder_id: int):
    """Mark a reminder as completed."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reminders SET status = 'completed' 
        WHERE id = ?
    """, (reminder_id,))
    conn.commit()
    conn.close()
    logger.info(f"Reminder {reminder_id} marked as completed")


def delete_reminder(reminder_id: int):
    """Delete a reminder."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
    logger.info(f"Reminder {reminder_id} deleted")


def get_reminders_needing_10m_notification() -> List[Dict]:
    """Get reminders that are 10 minutes away and haven't been notified."""
    from datetime import timedelta
    conn = _get_conn()
    cursor = conn.cursor()
    
    now = datetime.now()
    ten_min_later = (now + timedelta(minutes=10)).isoformat()
    
    cursor.execute("""
        SELECT * FROM reminders 
        WHERE event_time <= ? AND notified_10m = 0 AND status != 'completed'
        ORDER BY event_time ASC
    """, (ten_min_later,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_reminders_needing_event_notification() -> List[Dict]:
    """Get reminders that are at event time and haven't been notified."""
    from datetime import timedelta
    conn = _get_conn()
    cursor = conn.cursor()
    
    now = datetime.now()
    now_str = now.isoformat()
    
    cursor.execute("""
        SELECT * FROM reminders 
        WHERE event_time <= ? AND notified_event = 0 AND status != 'completed'
        ORDER BY event_time ASC
    """, (now_str,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_reminder_stats() -> Dict:
    """Get statistics about reminders."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    stats = {}
    
    cursor.execute("SELECT COUNT(*) FROM reminders")
    stats['total'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'pending'")
    stats['pending'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'notified_10m'")
    stats['notified_10m'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'notified_event'")
    stats['notified_event'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'completed'")
    stats['completed'] = cursor.fetchone()[0]
    
    conn.close()
    return stats


# Initialize on import
init_reminder_db()
