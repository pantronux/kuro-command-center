"""Alert deduplication and Telegram DLQ integration for Market Sentinel V2."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from kuro_backend.market_v2.freshness import utc_now_iso
from kuro_backend.market_v2.schemas import MarketAlert, MarketSentinelReport, market_v2_db_path


TelegramSender = Callable[[str, Optional[str]], bool]


class MarketAlertStore:
    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else market_v2_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_v2_alerts (
                    alert_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    symbol TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_v2_alert_fp ON market_v2_alerts(username, fingerprint, expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_v2_alert_user ON market_v2_alerts(username, created_at DESC)")

    def create_or_suppress(
        self,
        *,
        report: MarketSentinelReport,
        channel: str = "dashboard",
        ttl_minutes: int = 30,
    ) -> MarketAlert:
        fingerprint = self.fingerprint(report)
        now = utc_now_iso()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=max(1, int(ttl_minutes or 30)))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        existing = self.find_active(report.username, fingerprint)
        if existing:
            return existing.model_copy(update={"status": "suppressed"})
        severity = "warning" if report.signal.contradiction_detected or report.signal.stale_data_detected else "info"
        if report.confidence >= 0.8 and not report.insufficient_evidence:
            severity = "critical"
        alert = MarketAlert(
            username=report.username,
            workspace_id=report.workspace_id,
            symbol=report.symbol,
            fingerprint=fingerprint,
            severity=severity,
            channel=channel if channel in {"dashboard", "telegram", "both"} else "dashboard",
            title=f"Market V2 {report.symbol}: {report.signal.direction}",
            message=report.summary,
            status="active",
            created_at=now,
            expires_at=expires,
            metadata_json={"report_id": report.report_id, "confidence": report.confidence},
        )
        self.save(alert)
        return alert

    def publish(self, alert: MarketAlert, *, telegram_sender: Optional[TelegramSender] = None) -> MarketAlert:
        if alert.status == "suppressed":
            return alert
        if alert.channel not in {"telegram", "both"}:
            return alert
        sender = telegram_sender
        if sender is None:
            from kuro_backend import telegram_notifier

            def _send(text: str, chat_id: Optional[str] = None) -> bool:
                return telegram_notifier.send_message(text)

            sender = _send
        ok = False
        try:
            ok = bool(sender(alert.message, None))
        except Exception as exc:
            self._log_telegram_dlq(alert, str(exc))
        if not ok:
            self._log_telegram_dlq(alert, "market alert telegram send failed")
            updated = alert.model_copy(update={"status": "failed"})
            self.save(updated)
            return updated
        updated = alert.model_copy(update={"status": "sent"})
        self.save(updated)
        return updated

    def save(self, alert: MarketAlert) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_v2_alerts (
                    alert_id, username, workspace_id, symbol, fingerprint,
                    severity, channel, title, message, status, created_at,
                    expires_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.alert_id,
                    alert.username,
                    alert.workspace_id,
                    alert.symbol,
                    alert.fingerprint,
                    alert.severity,
                    alert.channel,
                    alert.title,
                    alert.message,
                    alert.status,
                    alert.created_at,
                    alert.expires_at,
                    json.dumps(alert.metadata_json, ensure_ascii=False, sort_keys=True),
                ),
            )

    def find_active(self, username: str, fingerprint: str) -> Optional[MarketAlert]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM market_v2_alerts
                WHERE username = ? AND fingerprint = ? AND expires_at > ?
                  AND status IN ('active', 'sent', 'failed')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (username, fingerprint, utc_now_iso()),
            ).fetchone()
        return self._row_to_alert(row) if row else None

    def list_alerts(self, *, username: str, limit: int = 50) -> List[MarketAlert]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_v2_alerts
                WHERE username = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (username, max(1, min(int(limit or 50), 200))),
            ).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def fingerprint(self, report: MarketSentinelReport) -> str:
        raw = f"{report.username}:{report.symbol}:{report.signal.direction}:{round(report.confidence, 1)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def _row_to_alert(self, row: sqlite3.Row) -> MarketAlert:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            metadata = {}
        return MarketAlert(
            alert_id=row["alert_id"],
            username=row["username"],
            workspace_id=row["workspace_id"],
            symbol=row["symbol"],
            fingerprint=row["fingerprint"],
            severity=row["severity"],
            channel=row["channel"],
            title=row["title"],
            message=row["message"],
            status=row["status"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            metadata_json=metadata if isinstance(metadata, dict) else {"value": metadata},
        )

    def _log_telegram_dlq(self, alert: MarketAlert, error: str) -> None:
        try:
            from kuro_backend import intelligence_db

            intelligence_db.log_failed_notification(
                payload_json=json.dumps(
                    {"chat_id": None, "text": alert.message, "source": "market_v2", "alert_id": alert.alert_id},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                error_message=error,
            )
        except Exception:
            return
