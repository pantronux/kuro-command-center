"""Kuro AI V6.0 "Sovereign" — Proactive anomaly event bus.

Central, dedup'd channel that all anomaly sources publish to:

  - ``dreaming_worker._run_reflection``  -> memory_inconsistency findings
  - ``dreaming_worker._run_cve_sentinel`` -> security_cve findings
  - ``main.hardware_sentinel_check``      -> hardware anomalies
  - ``fitness_service.check_fitness_anomalies`` -> fitness anomalies
  - ``memory_coordinator._maybe_emit_proactive_from_mutation`` -> write-path anomalies

The bus owns three cross-cutting concerns so no source re-implements them:

  1. Severity thresholding. Anything below ``warning`` is logged and dropped.
  2. Deduplication. Reuses the existing ``dream_notifications`` fingerprint
     table so a CVE seen last cycle doesn't re-page Master tonight.
  3. Dispatch. Uses :mod:`kuro_backend.telegram_notifier` on a background
     thread so the HTTP request / SQLite write path never blocks.

All public functions are safe to call from any thread; publish never raises.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Final, Optional, Tuple

logger = logging.getLogger(__name__)

_ENV_ENABLED: Final[str] = "KURO_PROACTIVE_ENABLED"
_ENV_TELEGRAM: Final[str] = "KURO_PROACTIVE_TELEGRAM_ENABLED"
_ENV_SEVERITY_FLOOR: Final[str] = "KURO_PROACTIVE_SEVERITY_FLOOR"

_SEVERITY_ORDER: Final[Tuple[str, ...]] = ("info", "warning", "critical")
_KINDS: Final[Tuple[str, ...]] = (
    "security_cve",
    "fitness_anomaly",
    "hardware",
    "memory_inconsistency",
    "generic",
)


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, "true" if default else "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _severity_rank(severity: str) -> int:
    try:
        return _SEVERITY_ORDER.index((severity or "info").lower())
    except ValueError:
        return 0


def _severity_floor_rank() -> int:
    raw = (os.getenv(_ENV_SEVERITY_FLOOR) or "warning").lower()
    return _severity_rank(raw)


@dataclass(frozen=True)
class ProactiveEvent:
    """A single anomaly observation ready to be published.

    Callers must provide a stable ``fingerprint_seed`` so dedup works across
    restarts — e.g. ``f"cve:{cve_id}:{target_id}"`` or ``f"hw:ram:>90"``.
    """

    kind: str
    severity: str
    title: str
    body: str
    fingerprint_seed: str
    context: Dict[str, Any] = field(default_factory=dict)

    def normalized_kind(self) -> str:
        return self.kind if self.kind in _KINDS else "generic"

    def fingerprint(self) -> str:
        seed = f"{self.normalized_kind()}|{self.fingerprint_seed}".encode("utf-8")
        return hashlib.sha1(seed).hexdigest()

    def format_telegram(self) -> str:
        prefix_map = {
            "critical": "[CRITICAL]",
            "warning": "[WARNING]",
            "info": "[INFO]",
        }
        prefix = prefix_map.get(self.severity.lower(), "[ALERT]")
        title = self.title.strip() or self.normalized_kind()
        body = self.body.strip()
        text = f"{prefix} {title}"
        if body:
            text = f"{text}\n{body}"
        return text[:3800]


def _should_notify(event: ProactiveEvent) -> bool:
    if _severity_rank(event.severity) < _severity_floor_rank():
        return False
    try:
        from kuro_backend import memory_manager
        memory_manager.init_short_term_db()
        if memory_manager.dream_notification_seen(event.fingerprint()):
            return False
    except Exception as exc:
        logger.warning("[PROACTIVE] dedup check failed: %s", exc)
    return True


def _mark_sent(event: ProactiveEvent) -> None:
    try:
        from kuro_backend import memory_manager
        memory_manager.mark_dream_notification(
            event.fingerprint(), event.normalized_kind(), event.kind,
        )
    except Exception as exc:
        logger.warning("[PROACTIVE] dedup mark failed: %s", exc)


def _dispatch_telegram(event: ProactiveEvent, dry_run: bool) -> bool:
    try:
        from kuro_backend import telegram_notifier
        sent = telegram_notifier.send_message(
            event.format_telegram(), dry_run=dry_run,
        )
    except Exception as exc:
        logger.warning("[PROACTIVE] telegram dispatch failed: %s", exc)
        return False
    if sent and not dry_run:
        _mark_sent(event)
    return sent


def publish(event: ProactiveEvent, *, dry_run: bool = False) -> bool:
    """Publish a proactive event. Never raises; returns ``True`` when a
    Telegram notification was dispatched."""
    if not isinstance(event, ProactiveEvent):
        logger.warning("[PROACTIVE] non-event payload ignored")
        return False
    if not _env_bool(_ENV_ENABLED, True):
        logger.info("[PROACTIVE] disabled via %s", _ENV_ENABLED)
        return False
    logger.info(
        "[PROACTIVE] event kind=%s severity=%s title=%.80s",
        event.normalized_kind(), event.severity, event.title,
    )
    if not _env_bool(_ENV_TELEGRAM, True):
        return False
    if not _should_notify(event):
        return False
    return _dispatch_telegram(event, dry_run=dry_run)


def publish_async(event: ProactiveEvent, *, dry_run: bool = False) -> None:
    """Fire-and-forget wrapper that runs ``publish`` on a daemon thread so
    the caller's hot path is never blocked by Telegram I/O or SQLite."""
    if not _env_bool(_ENV_ENABLED, True):
        return
    thread = threading.Thread(
        target=publish, args=(event,), kwargs={"dry_run": dry_run}, daemon=True,
    )
    thread.start()


def make_event(
    *,
    kind: str,
    severity: str,
    title: str,
    body: str = "",
    fingerprint_seed: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> ProactiveEvent:
    """Helper with validation so callers can't accidentally pass a bad kind."""
    safe_kind = kind if kind in _KINDS else "generic"
    safe_severity = severity if severity in _SEVERITY_ORDER else "info"
    seed = fingerprint_seed or f"{safe_kind}:{title}"
    return ProactiveEvent(
        kind=safe_kind,
        severity=safe_severity,
        title=title,
        body=body,
        fingerprint_seed=seed,
        context=context or {},
    )


__all__ = [
    "ProactiveEvent",
    "make_event",
    "publish",
    "publish_async",
]
