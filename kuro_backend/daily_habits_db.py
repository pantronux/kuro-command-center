"""
Kuro Daily Habits Database - SQLite-based Habit Tracking
========================================================
Tracks daily habits with done/pending status, categories, and completion history.
Supports midnight reset and end-of-day reporting.
"""
import sqlite3
import logging
import os
import threading
from datetime import datetime, date
from typing import List, Dict, Optional
from kuro_backend.tools import PROJECT_ROOT

logger = logging.getLogger(__name__)

HABITS_DB = os.path.join(PROJECT_ROOT, "kuro_habits.db")
_lock = threading.Lock()


def _get_conn():
    """Get SQLite connection for habits database."""
    conn = sqlite3.connect(HABITS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_habits_db():
    """Initialize habits database with schema."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            category TEXT DEFAULT 'General',
            is_done INTEGER DEFAULT 0,
            last_completed_date TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            google_task_id TEXT DEFAULT ''
        )
    """)
    
    # Completion history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completion_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            completed_date TEXT NOT NULL,
            completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (habit_id) REFERENCES daily_habits(id)
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("Daily habits database initialized.")


def add_habit(title: str, scheduled_time: str, category: str = "General") -> int:
    """Add a new daily habit."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO daily_habits (title, scheduled_time, category)
        VALUES (?, ?, ?)
    """, (title, scheduled_time, category))
    habit_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Habit added: {title} at {scheduled_time} (ID: {habit_id})")
    return habit_id


def update_habit(habit_id: int, title: str = None, scheduled_time: str = None, category: str = None):
    """Update an existing habit."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    if title is not None:
        cursor.execute("UPDATE daily_habits SET title = ? WHERE id = ?", (title, habit_id))
    if scheduled_time is not None:
        cursor.execute("UPDATE daily_habits SET scheduled_time = ? WHERE id = ?", (scheduled_time, habit_id))
    if category is not None:
        cursor.execute("UPDATE daily_habits SET category = ? WHERE id = ?", (category, habit_id))
    
    conn.commit()
    conn.close()
    logger.info(f"Habit {habit_id} updated.")


def delete_habit(habit_id: int):
    """Delete a habit and its history."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM completion_history WHERE habit_id = ?", (habit_id,))
    cursor.execute("DELETE FROM daily_habits WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()
    logger.info(f"Habit {habit_id} deleted.")


def get_all_habits() -> List[Dict]:
    """Get all daily habits."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_habits ORDER BY scheduled_time ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_todays_habits() -> List[Dict]:
    """Get all habits for today with their status."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_habits ORDER BY scheduled_time ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_habit_done(habit_id: int) -> bool:
    """Mark a habit as done for today."""
    today = date.today().isoformat()
    now = datetime.now().isoformat()
    
    conn = _get_conn()
    cursor = conn.cursor()
    
    # Check if already done today
    cursor.execute("SELECT is_done, last_completed_date FROM daily_habits WHERE id = ?", (habit_id,))
    row = cursor.fetchone()
    if row and row['last_completed_date'] == today:
        conn.close()
        return False  # Already done today
    
    cursor.execute("""
        UPDATE daily_habits 
        SET is_done = 1, last_completed_date = ? 
        WHERE id = ?
    """, (today, habit_id))
    
    # Log to completion history
    cursor.execute("""
        INSERT INTO completion_history (habit_id, completed_date, completed_at)
        VALUES (?, ?, ?)
    """, (habit_id, today, now))
    
    conn.commit()
    conn.close()
    logger.info(f"Habit {habit_id} marked as done for {today}")
    return True


def mark_habit_undone(habit_id: int):
    """Unmark a habit (set back to pending)."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE daily_habits 
        SET is_done = 0, last_completed_date = '' 
        WHERE id = ?
    """, (habit_id,))
    conn.commit()
    conn.close()
    logger.info(f"Habit {habit_id} marked as undone.")


def reset_all_habits():
    """Midnight reset: Set all is_done to False."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_habits SET is_done = 0, last_completed_date = ''")
    conn.commit()
    conn.close()
    logger.info("All habits reset for new day.")


def get_completion_stats() -> Dict:
    """Get today's completion statistics."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM daily_habits")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM daily_habits WHERE is_done = 1")
    done = cursor.fetchone()[0]
    
    pending = total - done
    percentage = round((done / total * 100), 1) if total > 0 else 0
    
    conn.close()
    return {
        "total": total,
        "done": done,
        "pending": pending,
        "percentage": percentage
    }


def get_end_of_day_report() -> str:
    """Generate a narrative end-of-day report."""
    habits = get_all_habits()
    stats = get_completion_stats()
    
    if not habits:
        return "Master Irfan, tidak ada habit yang tercatat hari ini."
    
    report_parts = [f"Laporan hari ini, Master Irfan:"]
    
    for h in habits:
        status = "✅ Done" if h['is_done'] else "⏳ Pending"
        report_parts.append(f"  - {h['title']} ({h['category']}): {status}")
    
    report_parts.append(f"\nOverall progress: {stats['percentage']}% ({stats['done']}/{stats['total']})")
    
    if stats['percentage'] >= 80:
        report_parts.append("Excellent work today, Master! Jangan lupa istirahat.")
    elif stats['percentage'] >= 50:
        report_parts.append("Good progress, Master. Masih ada yang bisa diselesaikan besok.")
    else:
        report_parts.append("Hari yang cukup sibuk, Master. Istirahat yang cukup ya.")
    
    return "\n".join(report_parts)


def get_habit_by_title(title: str) -> Optional[Dict]:
    """Find a habit by title (fuzzy match)."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_habits WHERE LOWER(title) LIKE LOWER(?)", (f"%{title}%",))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_weekly_stats() -> Dict:
    """Get completion stats for the past 7 days."""
    from datetime import timedelta
    conn = _get_conn()
    cursor = conn.cursor()
    
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    
    cursor.execute("""
        SELECT completed_date, COUNT(*) as count 
        FROM completion_history 
        WHERE completed_date >= ?
        GROUP BY completed_date
        ORDER BY completed_date DESC
    """, (week_ago,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return {
        "daily_completions": [dict(r) for r in rows],
        "total_this_week": sum(r['count'] for r in rows)
    }


# Initialize on import
init_habits_db()
