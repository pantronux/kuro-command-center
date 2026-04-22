"""
Deprecated shim — SQLite reminders live in `kuro_backend.services.core_service` only.

--- Header Doc ---
Purpose: Backwards-compat re-export for legacy callers that imported the old flat module.
Caller: Legacy tests / scripts that pre-date services/core_service.
Dependencies: kuro_backend.services.core_service.
Main Functions: Re-exports REMINDER_DB_PATH + helper aliases.
Side Effects: None beyond re-export.
"""
from kuro_backend.services.core_service import (
    REMINDER_DB_PATH as REMINDER_DB,
    add_reminder,
    delete_reminder,
    get_pending_reminders,
    get_reminder_by_id,
    get_reminder_history,
    get_reminder_stats,
    get_reminders_needing_10m_notification,
    get_reminders_needing_event_notification,
    get_upcoming_reminders,
    mark_completed,
    mark_notified_10m,
    mark_notified_event,
    normalize_reminder_row,
    update_reminder_status,
)


def init_reminder_db() -> None:
    """No-op: `core_service` initializes on import."""
