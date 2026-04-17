"""
Kuro AI V6.0 Sovereign — Habit & reminder mutations + reads. Storage is exclusively in
`kuro_backend.services.core_service` (single SQLite writer).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from kuro_backend.services import core_service as cs
from kuro_backend.services.schemas import ReminderRecord


def bump_data_revision() -> None:
    cs.bump_data_revision()


def get_data_revision() -> int:
    return cs.get_data_revision()


def add_reminder(
    event_name: str,
    event_time: str,
    description: str = "",
    source: str = "kuro",
    context: str = "",
) -> int:
    return cs.add_reminder_svc(
        event_name=event_name,
        event_time=event_time,
        description=description,
        source=source,
        context=context,
    )


def delete_reminder(reminder_id: int) -> None:
    cs.delete_reminder_svc(reminder_id)


def mark_notified_10m(reminder_id: int) -> None:
    cs.mark_notified_10m_svc(reminder_id)


def mark_notified_event(reminder_id: int) -> None:
    cs.mark_notified_event_svc(reminder_id)


def mark_reminder_completed(reminder_id: int) -> None:
    cs.mark_reminder_completed_svc(reminder_id)


def add_habit(title: str, scheduled_time: str, category: str = "General") -> int:
    return cs.add_habit_svc(title, scheduled_time, category)


def update_habit(habit_id: int, **kwargs: Any) -> None:
    cs.update_habit_svc(habit_id, **kwargs)


def delete_habit(habit_id: int) -> None:
    cs.delete_habit_svc(habit_id)


def mark_habit_done(habit_id: int) -> bool:
    return cs.mark_habit_done_svc(habit_id)


def mark_habit_undone(habit_id: int) -> None:
    cs.mark_habit_undone_svc(habit_id)


def toggle_habit_log_for_date(habit_id: int, log_date: str, new_status: int) -> None:
    cs.toggle_habit_log_for_date_svc(habit_id, log_date, new_status)


def reset_all_habits() -> None:
    cs.reset_all_habits_svc()


def save_ai_evaluation(
    habit_id: Optional[int],
    period_type: str,
    period_start: str,
    period_end: str,
    overall_score: float,
    evaluation_text: str,
) -> None:
    cs.save_ai_evaluation_svc(
        habit_id,
        period_type,
        period_start,
        period_end,
        overall_score,
        evaluation_text,
    )


def _validate_reminder_rows(rows: List[Dict]) -> List[Dict]:
    return [ReminderRecord.model_validate(d).model_dump(mode="json") for d in rows]


def get_upcoming_reminders(limit: int = 20) -> List[Dict]:
    return cs.list_reminders_upcoming_validated(limit)


def get_reminder_history(limit: int = 50) -> List[Dict]:
    return cs.list_reminders_history_validated(limit)


def get_reminder_stats() -> Dict:
    return cs.get_reminder_stats_validated()


def get_reminders_needing_10m_notification() -> List[Dict]:
    return _validate_reminder_rows(cs.get_reminders_needing_10m_notification())


def get_reminders_needing_event_notification() -> List[Dict]:
    return _validate_reminder_rows(cs.get_reminders_needing_event_notification())


def get_pending_reminders() -> List[Dict]:
    return _validate_reminder_rows(cs.get_pending_reminders())
