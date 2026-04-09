"""Pydantic v2 schemas for habits & reminders (API / tool boundaries)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, field_validator


class ReminderRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    event_name: str
    event_time: str
    description: str = ""
    status: str = "pending"
    source: str = "web"
    context: Union[str, Dict[str, Any], List[Any], None] = ""
    created_at: Optional[str] = None
    notified_10m: int = 0
    notified_event: int = 0

    @field_validator("context", mode="before")
    @classmethod
    def parse_context(cls, v: Any) -> Any:
        if v is None:
            return ""
        if not isinstance(v, str):
            return v
        t = v.strip()
        if t.startswith("{") or t.startswith("["):
            try:
                parsed = json.loads(t)
                return parsed if isinstance(parsed, (dict, list)) else str(parsed)
            except json.JSONDecodeError:
                return v
        return v


class ReminderStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = 0
    pending: int = 0
    notified_10m: int = 0
    notified_event: int = 0
    completed: int = 0


class HabitRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    scheduled_time: str
    category: str = "General"
    is_done: int = 0
    last_completed_date: str = ""
    created_at: Optional[str] = None
    google_task_id: str = ""
    target_per_month: int = 30
    target_per_week: int = 7

    @field_validator("last_completed_date", "google_task_id", mode="before")
    @classmethod
    def _none_to_empty(cls, v: Any) -> Any:
        return "" if v is None else v


class HabitCompletionStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = 0
    done: int = 0
    pending: int = 0
    percentage: float = 0.0


class HabitGridRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    category: str
    completed: int
    target: int
    percentage: float
    daily_log: Dict[int, int]

    @field_validator("daily_log", mode="before")
    @classmethod
    def _coerce_daily_keys(cls, v: Any) -> Dict[int, int]:
        if not isinstance(v, dict):
            return {}
        out: Dict[int, int] = {}
        for k, val in v.items():
            out[int(k)] = int(val)
        return out


class MonthlyHabitPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    days_in_month: int
    habits: List[HabitGridRow]
    daily_totals: Dict[int, int]

    @field_validator("daily_totals", mode="before")
    @classmethod
    def _coerce_totals(cls, v: Any) -> Dict[int, int]:
        if not isinstance(v, dict):
            return {}
        return {int(k): int(val) for k, val in v.items()}

    overall_stats: Dict[str, Union[int, float]]


class WeeklyHabitPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    week: int
    week_start: str
    week_end: str
    day_names: List[str]
    habits: List[HabitGridRow]
    daily_totals: Dict[int, int]

    @field_validator("daily_totals", mode="before")
    @classmethod
    def _coerce_week_totals(cls, v: Any) -> Dict[int, int]:
        if not isinstance(v, dict):
            return {}
        return {int(k): int(val) for k, val in v.items()}

    overall_stats: Dict[str, Union[int, float]]


class AiEvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    habit_id: Optional[int] = None
    period_type: str
    period_start: str
    period_end: str
    overall_score: float = 0.0
    evaluation_text: str = ""
    generated_at: Optional[str] = None
