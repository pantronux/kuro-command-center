"""Freshness helpers for Market Sentinel V2."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: object) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def freshness_seconds(observed_at: object, *, now: Optional[datetime] = None) -> Optional[float]:
    parsed = parse_timestamp(observed_at)
    if parsed is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - parsed).total_seconds())


def is_stale(seconds: Optional[float], *, threshold_seconds: float) -> bool:
    if seconds is None:
        return True
    return seconds > threshold_seconds


def downgrade_confidence(confidence: float, *, stale: bool) -> float:
    if not stale:
        return max(0.0, min(1.0, confidence))
    return round(max(0.0, min(1.0, confidence * 0.55)), 3)
