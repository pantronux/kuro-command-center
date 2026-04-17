"""Kuro AI V6.0 "Sovereign" — Fitness anomaly sentinel.

Reads a local JSON drop (``~/.kuro/fitness_latest.json``) written by whatever
wearable ingest pipeline Master is running (Garmin/Apple/etc) and emits
:class:`kuro_backend.proactive_events.ProactiveEvent` instances when the
metrics cross physiologically meaningful thresholds.

File contract::

    {
      "resting_hr": 58,
      "sleep_hours": 6.4,
      "recovery_score": 72,
      "last_sync": "2026-04-17T07:30:00Z",
      "history": [
        {"date": "2026-04-16", "resting_hr": 85},
        {"date": "2026-04-15", "resting_hr": 82}
      ]
    }

The module never raises. Missing file, malformed JSON, or an empty payload
all translate to an empty event list.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ENV_ENABLED = "KURO_FITNESS_ENABLED"
_ENV_PATH = "KURO_FITNESS_DATA_PATH"
_DEFAULT_PATH = "~/.kuro/fitness_latest.json"


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, "true" if default else "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _data_path() -> Path:
    raw = os.getenv(_ENV_PATH) or _DEFAULT_PATH
    return Path(os.path.expanduser(raw))


def _load_snapshot() -> Optional[Dict[str, Any]]:
    path = _data_path()
    if not path.exists():
        logger.debug("[FITNESS] snapshot missing at %s", path)
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("[FITNESS] failed to parse %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("[FITNESS] %s is not a JSON object", path)
        return None
    return data


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _consecutive_high_resting_hr(snapshot: Dict[str, Any], threshold: int) -> bool:
    """Return True when today and the previous day both exceed ``threshold``."""
    history = snapshot.get("history") or []
    if not isinstance(history, list) or len(history) < 1:
        return False
    today_hr = snapshot.get("resting_hr")
    try:
        today_val = float(today_hr)
    except (TypeError, ValueError):
        return False
    if today_val <= threshold:
        return False
    prev_entry = history[0] if isinstance(history[0], dict) else None
    if not prev_entry:
        return False
    try:
        prev_val = float(prev_entry.get("resting_hr"))
    except (TypeError, ValueError):
        return False
    return prev_val > threshold


def check_fitness_anomalies() -> List["ProactiveEvent"]:
    """Evaluate the latest snapshot against the documented thresholds.

    Returns a list of :class:`ProactiveEvent` ready for
    :func:`kuro_backend.proactive_events.publish`.
    """
    from kuro_backend import proactive_events

    if not _env_bool(_ENV_ENABLED, False):
        logger.debug("[FITNESS] disabled via %s", _ENV_ENABLED)
        return []
    snapshot = _load_snapshot()
    if not snapshot:
        return []

    events: List[proactive_events.ProactiveEvent] = []
    day_stamp = (snapshot.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    resting_hr = snapshot.get("resting_hr")
    if _consecutive_high_resting_hr(snapshot, threshold=80):
        events.append(proactive_events.make_event(
            kind="fitness_anomaly",
            severity="warning",
            title=f"Resting heart rate high ({resting_hr} bpm)",
            body=(
                "Resting HR has been above 80 bpm for two consecutive days. "
                "Consider lighter training and hydration, Master."
            ),
            fingerprint_seed=f"fitness:resting_hr:{day_stamp}",
            context={"resting_hr": resting_hr},
        ))

    try:
        sleep_hours = float(snapshot.get("sleep_hours"))
    except (TypeError, ValueError):
        sleep_hours = None  # type: ignore
    if isinstance(sleep_hours, float) and sleep_hours < 5.0:
        events.append(proactive_events.make_event(
            kind="fitness_anomaly",
            severity="warning",
            title=f"Short sleep detected ({sleep_hours:.1f}h)",
            body=(
                "Less than 5 hours of sleep last night. Suggesting a lighter "
                "cognitive load today."
            ),
            fingerprint_seed=f"fitness:sleep:{day_stamp}",
            context={"sleep_hours": sleep_hours},
        ))

    try:
        recovery = float(snapshot.get("recovery_score"))
    except (TypeError, ValueError):
        recovery = None  # type: ignore
    if isinstance(recovery, float) and recovery < 30.0:
        events.append(proactive_events.make_event(
            kind="fitness_anomaly",
            severity="critical",
            title=f"Recovery score critically low ({recovery:.0f})",
            body=(
                "Recovery score is below 30. Recommend a rest day and a check "
                "for illness or overtraining."
            ),
            fingerprint_seed=f"fitness:recovery:{day_stamp}",
            context={"recovery_score": recovery},
        ))

    last_sync_dt = _parse_iso(snapshot.get("last_sync"))
    if last_sync_dt:
        delta_hours = (
            datetime.now(timezone.utc) - last_sync_dt
        ).total_seconds() / 3600.0
        if delta_hours > 48.0:
            events.append(proactive_events.make_event(
                kind="fitness_anomaly",
                severity="info",
                title=f"Wearable offline for {delta_hours:.0f}h",
                body=(
                    "No wearable sync in more than 48 hours. Consider "
                    "reconnecting the device."
                ),
                fingerprint_seed=f"fitness:stale:{day_stamp}",
                context={"hours_since_sync": round(delta_hours, 1)},
            ))

    return events


def run_fitness_sentinel() -> int:
    """Scheduler entry point. Publishes every anomaly found. Returns the
    number of events dispatched.

    Also emits STATUS_TICKER broadcasts so the HUD shows the Sebastian
    sentinel sweep in real time.
    """
    from kuro_backend import proactive_events
    from kuro_backend import dashboard_broadcast

    if not _env_bool(_ENV_ENABLED, False):
        return 0
    dashboard_broadcast.schedule_ui_command(
        "STATUS_TICKER",
        {"status": "SCANNING", "source": "FITNESS"},
    )
    dispatched = 0
    try:
        for event in check_fitness_anomalies():
            if proactive_events.publish(event):
                dispatched += 1
        if dispatched:
            logger.info("[FITNESS] published %d anomaly event(s)", dispatched)
        return dispatched
    finally:
        ticker_status = "ALERT" if dispatched else "IDLE"
        detail = (
            f"{dispatched} anomaly" + ("s" if dispatched != 1 else "")
            if dispatched
            else ""
        )
        dashboard_broadcast.schedule_ui_command(
            "STATUS_TICKER",
            {"status": ticker_status, "source": "FITNESS", "detail": detail},
        )


__all__ = [
    "check_fitness_anomalies",
    "run_fitness_sentinel",
]
