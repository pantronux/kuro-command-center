"""
Kuro Daily Habits Database V2.0 - SQLite-based Habit Tracking
==============================================================
Tracks daily habits with done/pending status, categories, and completion history.
Supports monthly/weekly grid visualization, AI evaluations, and midnight reset.

V2.0 Changes:
- Added habit_logs table for daily log entries (date-based tracking)
- Added target_per_month and target_per_week to habits table
- Added ai_evaluations table for caching Gemini 3 monthly/weekly reports
- Added monthly/weekly analytics functions
"""
import sqlite3
import logging
import os
import threading
from datetime import datetime, date, timedelta
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
    """Initialize habits database with V2.0 schema."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    # V2.0: Updated habits table with target tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            category TEXT DEFAULT 'General',
            is_done INTEGER DEFAULT 0,
            last_completed_date TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            google_task_id TEXT DEFAULT '',
            target_per_month INTEGER DEFAULT 30,
            target_per_week INTEGER DEFAULT 7
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
            completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (habit_id) REFERENCES daily_habits(id)
        )
    """)
    
    # V2.0: New habit_logs table for daily log entries
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            status INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (habit_id) REFERENCES daily_habits(id),
            UNIQUE(habit_id, log_date)
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
            overall_score REAL DEFAULT 0,
            evaluation_text TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (habit_id) REFERENCES daily_habits(id),
            UNIQUE(habit_id, period_type, period_start, period_end)
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("Daily habits database V2.0 initialized.")


def add_habit(title: str, scheduled_time: str, category: str = "General", 
              target_per_month: int = 30, target_per_week: int = 7) -> int:
    """Add a new daily habit with target settings."""
    conn = _get_conn()
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
    conn = _get_conn()
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
    conn = _get_conn()
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
    conn = _get_conn()
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
    
    conn = _get_conn()
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
    grid_data = {}
    daily_totals = {day: 0 for day in range(1, days_in_month + 1)}
    
    for habit in habits:
        grid_data[habit['id']] = {day: 0 for day in range(1, days_in_month + 1)}
    
    for log in logs:
        habit_id = log['habit_id']
        log_date = datetime.fromisoformat(log['log_date']).date()
        if log_date.month == month and log_date.year == year:
            day = log_date.day
            if habit_id in grid_data:
                grid_data[habit_id][day] = log['status']
                if log['status'] == 1:
                    daily_totals[day] = daily_totals.get(day, 0) + 1
    
    # Calculate per-habit monthly stats
    habit_stats = []
    total_possible = len(habits) * days_in_month
    total_completed = 0
    
    for habit in habits:
        habit_id = habit['id']
        completed = sum(1 for day, status in grid_data[habit_id].items() if status == 1)
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
    conn = _get_conn()
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
    grid_data = {}
    daily_totals = {i: 0 for i in range(7)}  # 0=Mon, 6=Sun
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    for habit in habits:
        grid_data[habit['id']] = {i: 0 for i in range(7)}
    
    for log in logs:
        habit_id = log['habit_id']
        log_date = datetime.fromisoformat(log['log_date']).date()
        if week_start <= log_date <= week_end:
            day_offset = (log_date - week_start).days
            if habit_id in grid_data and 0 <= day_offset <= 6:
                grid_data[habit_id][day_offset] = log['status']
                if log['status'] == 1:
                    daily_totals[day_offset] = daily_totals.get(day_offset, 0) + 1
    
    # Calculate per-habit weekly stats
    habit_stats = []
    total_possible = len(habits) * 7
    total_completed = 0
    
    for habit in habits:
        habit_id = habit['id']
        completed = sum(1 for day, status in grid_data[habit_id].items() if status == 1)
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
    conn = _get_conn()
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


def save_ai_evaluation(habit_id: Optional[int], period_type: str, 
                       period_start: str, period_end: str, 
                       overall_score: float, evaluation_text: str):
    """Save AI evaluation to cache."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO ai_evaluations 
        (habit_id, period_type, period_start, period_end, overall_score, evaluation_text)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (habit_id, period_type, period_start, period_end, overall_score, evaluation_text))
    conn.commit()
    conn.close()
    logger.info(f"AI evaluation saved for {period_type} {period_start} to {period_end}")


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


# Initialize on import
init_habits_db()
