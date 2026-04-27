"""
Kuro AI V6.0 Sovereign — kuro_backend.services.core_service — SINGLE SQLite writer for reminders + habits.

All other modules must use this API only (no direct sqlite3 to these DBs).

--- Header Doc ---
Purpose: Single SQLite writer for reminders/habits/SSoT revision + cross-DB init orchestration.
Caller: main.py routes, reminder_service, ssot_shortcuts, dreaming_worker, memory_coordinator (revision read).
Dependencies: sqlite3, schemas (pydantic), tools.PROJECT_ROOT, logger.
Main Functions: init_all_databases(), add_habit(), add_reminder(), bump_data_revision(), get_data_revision(), async helpers via services.async_adapter.
Side Effects: Writes to kuro_short_term.db (WAL); bumps cache-buster revision used by semantic_cache; cross-init calls finance/compliance/intelligence/auth DBs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from kuro_backend.tools import PROJECT_ROOT
from kuro_backend.services.schemas import (
    HabitCompletionStats,
    HabitRecord,
    MonthlyHabitPayload,
    ReminderRecord,
    ReminderStats,
    WeeklyHabitPayload,
)

logger = logging.getLogger(__name__)
logger.propagate = False

_write_lock = threading.Lock()
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None

SYNC_METADATA_KEY_REVISION = "data_revision"


def register_main_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once from FastAPI startup so bumps can schedule WebSocket broadcasts."""
    global _main_event_loop
    _main_event_loop = loop


def _notify_websocket_refresh(revision: int) -> None:
    loop = _main_event_loop
    if loop is None or not loop.is_running():
        return
    try:
        from kuro_backend import dashboard_broadcast

        asyncio.run_coroutine_threadsafe(
            dashboard_broadcast.broadcast_refresh(revision),
            loop,
        )
    except Exception as e:
        logger.debug("[SYNC] websocket schedule skipped: %s", e)


def bump_data_revision() -> None:
    """Increment persisted revision (habits DB) so all workers share one counter; then push WS."""
    new_val: int
    with _write_lock:
        conn = _conn_habits()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                """
                INSERT OR IGNORE INTO app_sync_metadata (key, value)
                VALUES (?, 0)
                """,
                (SYNC_METADATA_KEY_REVISION,),
            )
            cur.execute(
                """
                UPDATE app_sync_metadata
                SET value = value + 1,
                    updated_at = datetime('now')
                WHERE key = ?
                """,
                (SYNC_METADATA_KEY_REVISION,),
            )
            cur.execute(
                "SELECT value FROM app_sync_metadata WHERE key = ?",
                (SYNC_METADATA_KEY_REVISION,),
            )
            row = cur.fetchone()
            new_val = int(row[0]) if row else 0
            conn.commit()
        finally:
            conn.close()
    logger.info("[SYNC] Revision bumped to %s", new_val)
    _notify_websocket_refresh(new_val)


def get_data_revision() -> int:
    """Read current revision from SQLite (authoritative across workers)."""
    conn = _conn_habits()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM app_sync_metadata WHERE key = ?",
            (SYNC_METADATA_KEY_REVISION,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _resolve_db_path_with_env(
    env_keys: tuple[str, ...],
    default_filename: str,
    db_label: str,
) -> str:
    """Resolve DB path with explicit env precedence and startup diagnostics."""
    for key in env_keys:
        raw = os.getenv(key)
        if not raw:
            continue
        candidate = raw.strip()
        if not candidate:
            logger.warning("[DB_PATH] %s ignored empty value for env %s", db_label, key)
            continue
        expanded = os.path.expanduser(candidate)
        resolved = os.path.abspath(
            expanded if os.path.isabs(expanded) else os.path.join(PROJECT_ROOT, expanded)
        )
        logger.info("[DB_PATH] %s resolved from %s -> %s", db_label, key, resolved)
        return resolved

    fallback = os.path.abspath(os.path.join(PROJECT_ROOT, default_filename))
    logger.warning(
        "[DB_PATH] %s using fallback path %s (env keys missing: %s)",
        db_label,
        fallback,
        ", ".join(env_keys),
    )
    return fallback


def _resolve_reminder_db_path() -> str:
    return _resolve_db_path_with_env(
        ("KURO_REMINDERS_DB_PATH", "KURO_REMINDERS_DB"),
        "kuro_reminders.db",
        "reminders",
    )


REMINDER_DB_PATH = _resolve_reminder_db_path()
REMINDER_DB = REMINDER_DB_PATH  # backward compat alias
# lock consolidated in core_service


def _conn_reminders():
    """Get SQLite connection for reminder database."""
    conn = sqlite3.connect(REMINDER_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_reminders_schema():
    """Initialize reminder database with schema."""
    conn = _conn_reminders()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            event_time TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            source TEXT NOT NULL DEFAULT 'web',
            context TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            notified_10m INTEGER NOT NULL DEFAULT 0,
            notified_event INTEGER NOT NULL DEFAULT 0,
            CHECK (status IN ('pending', 'notified_10m', 'notified_event', 'completed')),
            CHECK (notified_10m IN (0, 1)),
            CHECK (notified_event IN (0, 1))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_event_time ON reminders(event_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status)")
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
        context: Additional context from Mem0 lookup
    
    Returns:
        The ID of the newly created reminder
    """
    conn = _conn_reminders()
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
    conn = _conn_reminders()
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
    conn = _conn_reminders()
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
    return [normalize_reminder_row(dict(r)) for r in rows]


def get_reminder_history(limit: int = 50) -> List[Dict]:
    """Get past reminders (completed or event time passed)."""
    conn = _conn_reminders()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        SELECT * FROM reminders 
        WHERE event_time <= ? OR status = 'completed'
        ORDER BY event_time DESC
        LIMIT ?
    """, (now, limit))
    rows = cursor.fetchall()
    if not rows:
        cursor.execute("SELECT COUNT(*) FROM reminders")
        total = cursor.fetchone()[0]
        logger.debug(
            "get_reminder_history: query returned 0 rows but reminders table has %s rows (db=%s)",
            total,
            REMINDER_DB,
        )
    conn.close()
    return [normalize_reminder_row(dict(r)) for r in rows]


def normalize_reminder_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure API/JSON-friendly values; parse context if it is JSON text."""
    out = dict(row)
    ctx = out.get("context")
    if isinstance(ctx, str) and ctx.strip():
        t = ctx.strip()
        if t.startswith("{") or t.startswith("["):
            try:
                parsed = json.loads(t)
                out["context"] = parsed if isinstance(parsed, (dict, list)) else str(parsed)
            except json.JSONDecodeError:
                logger.debug("reminder id=%s context not valid JSON (len=%s)", out.get("id"), len(t))
    return out


def get_reminder_by_id(reminder_id: int) -> Optional[Dict]:
    """Get a specific reminder by ID."""
    conn = _conn_reminders()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_reminder_status(reminder_id: int, status: str):
    """Update the status of a reminder."""
    conn = _conn_reminders()
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
    conn.commit()
    conn.close()
    logger.info(f"Reminder {reminder_id} status updated to: {status}")


def mark_notified_10m(reminder_id: int):
    """Mark that the 10-minute notification has been sent."""
    conn = _conn_reminders()
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
    conn = _conn_reminders()
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
    conn = _conn_reminders()
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
    conn = _conn_reminders()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
    logger.info(f"Reminder {reminder_id} deleted")


def get_reminders_needing_10m_notification() -> List[Dict]:
    """Get reminders that are 10 minutes away and haven't been notified."""
    from datetime import timedelta
    conn = _conn_reminders()
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
    conn = _conn_reminders()
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
    conn = _conn_reminders()
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


def _resolve_habits_db_path() -> str:
    return _resolve_db_path_with_env(
        ("KURO_HABITS_DB_PATH", "KURO_HABITS_DB"),
        "kuro_habits.db",
        "habits",
    )


HABITS_DB_PATH = _resolve_habits_db_path()
HABITS_DB = HABITS_DB_PATH  # backward compat alias
# lock consolidated


def _conn_habits():
    """Get SQLite connection for habits database."""
    conn = sqlite3.connect(HABITS_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_habits_schema():
    """Initialize habits database with V2.0 schema."""
    conn = _conn_habits()
    cursor = conn.cursor()
    
    # V2.0: Updated habits table with target tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'General',
            is_done INTEGER NOT NULL DEFAULT 0,
            last_completed_date TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            google_task_id TEXT NOT NULL DEFAULT '',
            target_per_month INTEGER NOT NULL DEFAULT 30,
            target_per_week INTEGER NOT NULL DEFAULT 7,
            CHECK (is_done IN (0, 1))
        )
    """)
    
    # Check if target columns exist, add if not
    cursor.execute("PRAGMA table_info(daily_habits)")
    columns = [row['name'] for row in cursor.fetchall()]
    if 'target_per_month' not in columns:
        cursor.execute("ALTER TABLE daily_habits ADD COLUMN target_per_month INTEGER DEFAULT 30")
    if 'target_per_week' not in columns:
        cursor.execute("ALTER TABLE daily_habits ADD COLUMN target_per_week INTEGER DEFAULT 7")
    
    # Completion history table (legacy)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completion_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            completed_date TEXT NOT NULL,
            completed_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (habit_id) REFERENCES daily_habits(id)
        )
    """)
    
    # V2.0: New habit_logs table for daily log entries
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            status INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (habit_id) REFERENCES daily_habits(id),
            UNIQUE(habit_id, log_date),
            CHECK (status IN (0, 1))
        )
    """)
    
    # V2.0: AI evaluations cache table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER,
            period_type TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            overall_score REAL NOT NULL DEFAULT 0,
            evaluation_text TEXT NOT NULL DEFAULT '',
            generated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (habit_id) REFERENCES daily_habits(id),
            UNIQUE(habit_id, period_type, period_start, period_end)
        )
    """)

    # Performance indices
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_habits_scheduled_time ON daily_habits(scheduled_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_habit_logs_log_date ON habit_logs(log_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_completion_history_date ON completion_history(completed_date)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_sync_metadata (
            key TEXT PRIMARY KEY NOT NULL,
            value INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cursor.execute(
        """
        INSERT OR IGNORE INTO app_sync_metadata (key, value)
        VALUES (?, 0)
        """,
        (SYNC_METADATA_KEY_REVISION,),
    )

    conn.commit()
    conn.close()
    logger.info("Daily habits database V2.0 initialized.")


def add_habit(title: str, scheduled_time: str, category: str = "General", 
              target_per_month: int = 30, target_per_week: int = 7) -> int:
    """Add a new daily habit with target settings."""
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO daily_habits (title, scheduled_time, category, target_per_month, target_per_week)
        VALUES (?, ?, ?, ?, ?)
    """, (title, scheduled_time, category, target_per_month, target_per_week))
    habit_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Habit added: {title} at {scheduled_time} (ID: {habit_id})")
    return habit_id


def update_habit(habit_id: int, title: str = None, scheduled_time: str = None, 
                 category: str = None, target_per_month: int = None, target_per_week: int = None):
    """Update an existing habit."""
    conn = _conn_habits()
    cursor = conn.cursor()
    
    if title is not None:
        cursor.execute("UPDATE daily_habits SET title = ? WHERE id = ?", (title, habit_id))
    if scheduled_time is not None:
        cursor.execute("UPDATE daily_habits SET scheduled_time = ? WHERE id = ?", (scheduled_time, habit_id))
    if category is not None:
        cursor.execute("UPDATE daily_habits SET category = ? WHERE id = ?", (category, habit_id))
    if target_per_month is not None:
        cursor.execute("UPDATE daily_habits SET target_per_month = ? WHERE id = ?", (target_per_month, habit_id))
    if target_per_week is not None:
        cursor.execute("UPDATE daily_habits SET target_per_week = ? WHERE id = ?", (target_per_week, habit_id))
    
    conn.commit()
    conn.close()
    logger.info(f"Habit {habit_id} updated.")


def delete_habit(habit_id: int):
    """Delete a habit and all its related data."""
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM completion_history WHERE habit_id = ?", (habit_id,))
    cursor.execute("DELETE FROM habit_logs WHERE habit_id = ?", (habit_id,))
    cursor.execute("DELETE FROM ai_evaluations WHERE habit_id = ?", (habit_id,))
    cursor.execute("DELETE FROM daily_habits WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()
    logger.info(f"Habit {habit_id} deleted.")


def get_all_habits() -> List[Dict]:
    """Get all daily habits."""
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_habits ORDER BY scheduled_time ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_todays_habits() -> List[Dict]:
    """Get all habits for today with their status."""
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_habits ORDER BY scheduled_time ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_habit_done(habit_id: int) -> bool:
    """Mark a habit as done for today."""
    today = date.today().isoformat()
    now = datetime.now().isoformat()
    
    conn = _conn_habits()
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
    
    # Log to completion history (legacy)
    cursor.execute("""
        INSERT INTO completion_history (habit_id, completed_date, completed_at)
        VALUES (?, ?, ?)
    """, (habit_id, today, now))
    
    # V2.0: Log to habit_logs table
    cursor.execute("""
        INSERT OR REPLACE INTO habit_logs (habit_id, log_date, status, notes)
        VALUES (?, ?, 1, ?)
    """, (habit_id, today, now))
    
    conn.commit()
    conn.close()
    logger.info(f"Habit {habit_id} marked as done for {today}")
    return True


def mark_habit_undone(habit_id: int):
    """Unmark a habit (set back to pending)."""
    today = date.today().isoformat()
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE daily_habits 
        SET is_done = 0, last_completed_date = '' 
        WHERE id = ?
    """, (habit_id,))
    # Update habit_logs for today
    cursor.execute("""
        UPDATE habit_logs SET status = 0 WHERE habit_id = ? AND log_date = ?
    """, (habit_id, today))
    conn.commit()
    conn.close()
    logger.info(f"Habit {habit_id} marked as undone.")


def toggle_habit_log_for_date(habit_id: int, log_date: str, new_status: int) -> None:
    """
    Set habit_logs status for a calendar date; keep completion_history in sync.
    Invalidates monthly AI evaluation cache for that month (best-effort).
    """
    from calendar import monthrange

    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO habit_logs (habit_id, log_date, status)
        VALUES (?, ?, ?)
        ON CONFLICT(habit_id, log_date) DO UPDATE SET status = ?
        """,
        (habit_id, log_date, new_status, new_status),
    )
    if new_status == 1:
        cursor.execute(
            """
            INSERT OR IGNORE INTO completion_history (habit_id, completed_date, completed_at)
            VALUES (?, ?, ?)
            """,
            (habit_id, log_date, datetime.now().isoformat()),
        )
    else:
        cursor.execute(
            "DELETE FROM completion_history WHERE habit_id = ? AND completed_date = ?",
            (habit_id, log_date),
        )
    conn.commit()
    conn.close()

    try:
        target_date = datetime.fromisoformat(log_date).date()
        year, month = target_date.year, target_date.month
        _, dim = monthrange(year, month)
        period_start = f"{year}-{month:02d}-01"
        period_end = f"{year}-{month:02d}-{dim:02d}"
        save_ai_evaluation(None, "monthly", period_start, period_end, 0, "")
    except Exception:
        pass


def reset_all_habits():
    """Midnight reset: Set all is_done to False."""
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_habits SET is_done = 0, last_completed_date = ''")
    conn.commit()
    conn.close()
    logger.info("All habits reset for new day.")


def get_completion_stats() -> Dict:
    """Get today's completion statistics."""
    conn = _conn_habits()
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
        return "Pantronux, tidak ada habit yang tercatat hari ini."
    
    report_parts = [f"Laporan hari ini, Pantronux:"]
    
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
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_habits WHERE LOWER(title) LIKE LOWER(?)", (f"%{title}%",))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_weekly_stats() -> Dict:
    """Get completion stats for the past 7 days."""
    conn = _conn_habits()
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


# ============================================
# V2.0: Monthly Analytics Functions
# ============================================

def get_monthly_data(year: int, month: int) -> Dict:
    """Get habit completion data for a specific month.
    
    Returns:
        {
            "habits": [...],
            "days_in_month": 30,
            "grid_data": {habit_id: {day: status}},
            "daily_totals": {day: count},
            "overall_stats": {...}
        }
    """
    from calendar import monthrange
    
    conn = _conn_habits()
    cursor = conn.cursor()
    
    # Get all habits
    cursor.execute("SELECT * FROM daily_habits ORDER BY scheduled_time ASC")
    habits = [dict(r) for r in cursor.fetchall()]
    
    # Get days in month
    _, days_in_month = monthrange(year, month)
    
    # Build date range for the month
    start_date = date(year, month, 1)
    end_date = date(year, month, days_in_month)
    
    # Get habit logs for this month
    cursor.execute("""
        SELECT habit_id, log_date, status 
        FROM habit_logs 
        WHERE log_date >= ? AND log_date <= ?
        ORDER BY log_date
    """, (start_date.isoformat(), end_date.isoformat()))
    
    logs = cursor.fetchall()
    
    # Build grid data: {habit_id: {day: status}}
    grid_data = {habit['id']: {day: 0 for day in range(1, days_in_month + 1)} for habit in habits}
    daily_totals = {day: 0 for day in range(1, days_in_month + 1)}
    
    for log in logs:
        habit_id = log['habit_id']
        log_date = datetime.fromisoformat(log['log_date']).date()
        # Redundant date check removed; SQL query already filters by start/end_date.
        day = log_date.day
        if habit_id in grid_data:
            grid_data[habit_id][day] = log['status']
            if log['status'] == 1:
                daily_totals[day] += 1
    
    # Calculate per-habit monthly stats
    habit_stats = []
    total_possible = len(habits) * days_in_month
    total_completed = 0
    
    for habit in habits:
        habit_id = habit['id']
        habit_grid = grid_data[habit_id]
        # status is 0 or 1, so sum is count of 1s
        completed = sum(habit_grid.values())
        target = habit.get('target_per_month', 30)
        percentage = round((completed / target * 100), 1) if target > 0 else 0
        total_completed += completed
        
        habit_stats.append({
            "id": habit_id,
            "title": habit['title'],
            "category": habit['category'],
            "completed": completed,
            "target": target,
            "percentage": min(percentage, 100),
            "daily_log": grid_data[habit_id]
        })
    
    overall_percentage = round((total_completed / total_possible * 100), 1) if total_possible > 0 else 0
    
    conn.close()
    
    return {
        "year": year,
        "month": month,
        "days_in_month": days_in_month,
        "habits": habit_stats,
        "daily_totals": daily_totals,
        "overall_stats": {
            "total_possible": total_possible,
            "total_completed": total_completed,
            "overall_percentage": overall_percentage
        }
    }


def get_weekly_data(year: int, week: int) -> Dict:
    """Get habit completion data for a specific ISO week.
    
    Returns:
        {
            "habits": [...],
            "week_start": date,
            "week_end": date,
            "grid_data": {habit_id: {day: status}},
            "daily_totals": {day: count},
            "overall_stats": {...}
        }
    """
    conn = _conn_habits()
    cursor = conn.cursor()
    
    # Get all habits
    cursor.execute("SELECT * FROM daily_habits ORDER BY scheduled_time ASC")
    habits = [dict(r) for r in cursor.fetchall()]
    
    # Calculate week start (Monday) and end (Sunday)
    jan1 = date(year, 1, 1)
    week_start = jan1 + timedelta(weeks=week - 1, days=-jan1.weekday())
    week_end = week_start + timedelta(days=6)
    
    # Get habit logs for this week
    cursor.execute("""
        SELECT habit_id, log_date, status 
        FROM habit_logs 
        WHERE log_date >= ? AND log_date <= ?
        ORDER BY log_date
    """, (week_start.isoformat(), week_end.isoformat()))
    
    logs = cursor.fetchall()
    
    # Build grid data: {habit_id: {day_offset: status}}
    grid_data = {habit['id']: {i: 0 for i in range(7)} for habit in habits}
    daily_totals = {i: 0 for i in range(7)}  # 0=Mon, 6=Sun
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    for log in logs:
        habit_id = log['habit_id']
        log_date = datetime.fromisoformat(log['log_date']).date()
        # Redundant date check removed; SQL query already filters by week_start/week_end.
        day_offset = (log_date - week_start).days
        if habit_id in grid_data and 0 <= day_offset <= 6:
            grid_data[habit_id][day_offset] = log['status']
            if log['status'] == 1:
                daily_totals[day_offset] += 1
    
    # Calculate per-habit weekly stats
    habit_stats = []
    total_possible = len(habits) * 7
    total_completed = 0
    
    for habit in habits:
        habit_id = habit['id']
        habit_grid = grid_data[habit_id]
        # status is 0 or 1, so sum is count of 1s
        completed = sum(habit_grid.values())
        target = habit.get('target_per_week', 7)
        percentage = round((completed / target * 100), 1) if target > 0 else 0
        total_completed += completed
        
        habit_stats.append({
            "id": habit_id,
            "title": habit['title'],
            "category": habit['category'],
            "completed": completed,
            "target": target,
            "percentage": min(percentage, 100),
            "daily_log": grid_data[habit_id]
        })
    
    overall_percentage = round((total_completed / total_possible * 100), 1) if total_possible > 0 else 0
    
    conn.close()
    
    return {
        "year": year,
        "week": week,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "day_names": day_names,
        "habits": habit_stats,
        "daily_totals": daily_totals,
        "overall_stats": {
            "total_possible": total_possible,
            "total_completed": total_completed,
            "overall_percentage": overall_percentage
        }
    }


# ============================================
# V2.0: AI Evaluation Cache Functions
# ============================================

def get_ai_evaluation(habit_id: Optional[int], period_type: str, 
                      period_start: str, period_end: str) -> Optional[Dict]:
    """Get cached AI evaluation for a period."""
    conn = _conn_habits()
    cursor = conn.cursor()
    
    if habit_id:
        cursor.execute("""
            SELECT * FROM ai_evaluations 
            WHERE habit_id = ? AND period_type = ? AND period_start = ? AND period_end = ?
        """, (habit_id, period_type, period_start, period_end))
    else:
        cursor.execute("""
            SELECT * FROM ai_evaluations 
            WHERE habit_id IS NULL AND period_type = ? AND period_start = ? AND period_end = ?
        """, (period_type, period_start, period_end))
    
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def clear_ai_evaluation_cache_for_period(
    habit_id: Optional[int],
    period_type: str,
    period_start: str,
    period_end: str,
) -> None:
    """
    Drop cached rows for this period so /api/habits/evaluation-cached cannot serve stale JSON
    before the new row is committed.
    """
    conn = _conn_habits()
    cursor = conn.cursor()
    if habit_id is None:
        cursor.execute(
            """
            DELETE FROM ai_evaluations
            WHERE habit_id IS NULL AND period_type = ? AND period_start = ? AND period_end = ?
            """,
            (period_type, period_start, period_end),
        )
    else:
        cursor.execute(
            """
            DELETE FROM ai_evaluations
            WHERE habit_id = ? AND period_type = ? AND period_start = ? AND period_end = ?
            """,
            (habit_id, period_type, period_start, period_end),
        )
    conn.commit()
    conn.close()


def save_ai_evaluation(habit_id: Optional[int], period_type: str, 
                       period_start: str, period_end: str, 
                       overall_score: float, evaluation_text: str):
    """Save AI evaluation to cache (invalidate prior row for this period first)."""
    clear_ai_evaluation_cache_for_period(habit_id, period_type, period_start, period_end)
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO ai_evaluations 
        (habit_id, period_type, period_start, period_end, overall_score, evaluation_text)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (habit_id, period_type, period_start, period_end, overall_score, evaluation_text))
    conn.commit()
    conn.close()
    logger.info(
        "[SYNC] AI evaluation row committed for %s %s — %s",
        period_type,
        period_start,
        period_end,
    )


def get_monthly_report_data(year: int, month: int) -> Dict:
    """Get formatted data for AI monthly report generation."""
    monthly_data = get_monthly_data(year, month)
    
    habits_summary = []
    for habit in monthly_data['habits']:
        habits_summary.append({
            "name": habit['title'],
            "category": habit['category'],
            "score": f"{habit['percentage']}%",
            "completed": habit['completed'],
            "target": habit['target']
        })
    
    return {
        "period": f"{get_month_name(month)} {year}",
        "period_type": "monthly",
        "period_start": f"{year}-{month:02d}-01",
        "period_end": f"{year}-{month:02d}-{monthly_data['days_in_month']:02d}",
        "overall_score": f"{monthly_data['overall_stats']['overall_percentage']}%",
        "habits": habits_summary
    }


def get_weekly_report_data(year: int, week: int) -> Dict:
    """Get formatted data for AI weekly report generation."""
    weekly_data = get_weekly_data(year, week)
    
    habits_summary = []
    for habit in weekly_data['habits']:
        habits_summary.append({
            "name": habit['title'],
            "category": habit['category'],
            "score": f"{habit['percentage']}%",
            "completed": habit['completed'],
            "target": habit['target']
        })
    
    return {
        "period": f"Week {week}, {year}",
        "period_type": "weekly",
        "period_start": weekly_data['week_start'],
        "period_end": weekly_data['week_end'],
        "overall_score": f"{weekly_data['overall_stats']['overall_percentage']}%",
        "habits": habits_summary
    }


def get_month_name(month: int) -> str:
    """Get month name in Indonesian."""
    months = {
        1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
        5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
        9: "September", 10: "Oktober", 11: "November", 12: "Desember"
    }
    return months.get(month, "Unknown")


def fetch_habit_activity_snapshot(days: int = 30) -> Dict[str, Any]:
    """Habit definitions + log/completion aggregates for LLM grounding."""
    habits = get_all_habits()
    today_stats = get_completion_stats()
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = _conn_habits()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM habit_logs WHERE log_date >= ? AND status = 1",
        (since,),
    )
    habit_log_done_count = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT h.title, hl.log_date, hl.status
        FROM habit_logs hl
        JOIN daily_habits h ON h.id = hl.habit_id
        WHERE hl.log_date >= ?
        ORDER BY hl.log_date DESC, h.title ASC
        LIMIT 120
        """,
        (since,),
    )
    habit_log_rows = [dict(r) for r in cursor.fetchall()]
    cursor.execute(
        "SELECT COUNT(*) FROM completion_history WHERE completed_date >= ?",
        (since,),
    )
    completion_history_count = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT h.title, ch.completed_date
        FROM completion_history ch
        JOIN daily_habits h ON h.id = ch.habit_id
        WHERE ch.completed_date >= ?
        ORDER BY ch.completed_date DESC, h.title ASC
        LIMIT 40
        """,
        (since,),
    )
    completion_samples = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {
        "window_days": days,
        "since": since,
        "habits": habits,
        "today_stats": today_stats,
        "habit_log_done_count": habit_log_done_count,
        "habit_log_rows": habit_log_rows,
        "completion_history_count": completion_history_count,
        "completion_samples": completion_samples,
    }


def init_all_databases() -> None:
    logger.info(
        "[DB_PATH] Active SQLite files -> reminders=%s habits=%s",
        REMINDER_DB_PATH,
        HABITS_DB_PATH,
    )
    _init_reminders_schema()
    _init_habits_schema()
    _migrate_habit_constraints()
    try:
        from kuro_backend import finance_db

        finance_db.init_db()
    except Exception as exc:
        logger.warning("[DB_PATH] finance_db init skipped: %s", exc)


def _migrate_habit_constraints() -> None:
    """Dedupe completion_history and enforce UNIQUE(habit_id, completed_date)."""
    conn = _conn_habits()
    try:
        c = conn.cursor()
        c.execute(
            """
            DELETE FROM completion_history
            WHERE id NOT IN (
                SELECT MIN(id) FROM completion_history GROUP BY habit_id, completed_date
            )
            """
        )
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_completion_habit_date "
            "ON completion_history(habit_id, completed_date)"
        )
        conn.commit()
    except Exception as e:
        logger.warning("completion_history migration skipped: %s", e)
    finally:
        conn.close()




# --- Pydantic-validated API (outbound) ---

def list_reminders_upcoming_validated(limit: int = 20) -> List[Dict[str, Any]]:
    return [ReminderRecord.model_validate(r).model_dump(mode="json") for r in get_upcoming_reminders(limit)]


def list_reminders_history_validated(limit: int = 50) -> List[Dict[str, Any]]:
    return [ReminderRecord.model_validate(r).model_dump(mode="json") for r in get_reminder_history(limit)]


def get_reminder_stats_validated() -> Dict[str, Any]:
    return ReminderStats.model_validate(get_reminder_stats()).model_dump(mode="json")


def list_habits_validated() -> List[Dict[str, Any]]:
    return [HabitRecord.model_validate(h).model_dump(mode="json") for h in get_all_habits()]


def get_completion_stats_validated() -> Dict[str, Any]:
    return HabitCompletionStats.model_validate(get_completion_stats()).model_dump(mode="json")


def get_monthly_data_validated(year: int, month: int) -> Dict[str, Any]:
    return MonthlyHabitPayload.model_validate(get_monthly_data(year, month)).model_dump(mode="json")


def get_weekly_data_validated(year: int, week: int) -> Dict[str, Any]:
    return WeeklyHabitPayload.model_validate(get_weekly_data(year, week)).model_dump(mode="json")


# --- Service mutations (bump revision) ---

def add_reminder_svc(
    event_name: str,
    event_time: str,
    description: str = "",
    source: str = "kuro",
    context: str = "",
) -> int:
    rid = add_reminder(event_name, event_time, description, source, context)
    bump_data_revision()
    return rid


def delete_reminder_svc(reminder_id: int) -> None:
    delete_reminder(reminder_id)
    bump_data_revision()


def mark_reminder_completed_svc(reminder_id: int) -> None:
    mark_completed(reminder_id)
    bump_data_revision()


def mark_notified_10m_svc(reminder_id: int) -> None:
    mark_notified_10m(reminder_id)
    bump_data_revision()


def mark_notified_event_svc(reminder_id: int) -> None:
    mark_notified_event(reminder_id)
    bump_data_revision()


def add_habit_svc(title: str, scheduled_time: str, category: str = "General") -> int:
    hid = add_habit(title, scheduled_time, category)
    bump_data_revision()
    return hid


def update_habit_svc(habit_id: int, **kwargs: Any) -> None:
    update_habit(habit_id, **kwargs)
    bump_data_revision()


def delete_habit_svc(habit_id: int) -> None:
    delete_habit(habit_id)
    bump_data_revision()


def mark_habit_done_svc(habit_id: int) -> bool:
    ok = mark_habit_done(habit_id)
    if ok:
        bump_data_revision()
    return ok


def mark_habit_undone_svc(habit_id: int) -> None:
    mark_habit_undone(habit_id)
    bump_data_revision()


def toggle_habit_log_for_date_svc(habit_id: int, log_date: str, new_status: int) -> None:
    toggle_habit_log_for_date(habit_id, log_date, new_status)
    bump_data_revision()


def reset_all_habits_svc() -> None:
    reset_all_habits()
    bump_data_revision()


def save_ai_evaluation_svc(
    habit_id: Optional[int],
    period_type: str,
    period_start: str,
    period_end: str,
    overall_score: float,
    evaluation_text: str,
) -> None:
    save_ai_evaluation(habit_id, period_type, period_start, period_end, overall_score, evaluation_text)
    bump_data_revision()


init_all_databases()
