"""
Deprecated shim — SQLite habits live in `kuro_backend.services.core_service` only.
"""
from kuro_backend.services.core_service import (
    HABITS_DB_PATH as HABITS_DB,
    add_habit,
    delete_habit,
    get_ai_evaluation,
    get_all_habits,
    get_completion_stats,
    get_end_of_day_report,
    get_habit_by_title,
    get_monthly_data,
    get_monthly_report_data,
    get_month_name,
    get_todays_habits,
    get_weekly_data,
    get_weekly_report_data,
    get_weekly_stats,
    mark_habit_done,
    mark_habit_undone,
    reset_all_habits,
    save_ai_evaluation,
    toggle_habit_log_for_date,
    update_habit,
)


def init_habits_db() -> None:
    """No-op: `core_service` initializes on import."""
