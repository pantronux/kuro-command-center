"""SQLite outbound queue and sender mappings for Telegram API V2."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from kuro_backend.telegram_v2.schemas import (
    TelegramOutboundMessage,
    TelegramSenderMapping,
    TelegramSenderMappingRequest,
    new_id,
    telegram_v2_db_path,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class TelegramV2QueueStore:
    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else telegram_v2_db_path()
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
                CREATE TABLE IF NOT EXISTS telegram_v2_outbound_queue (
                    message_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'telegram',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    sent_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_v2_sender_mappings (
                    mapping_id TEXT PRIMARY KEY,
                    telegram_user_id TEXT NOT NULL UNIQUE,
                    username TEXT NOT NULL,
                    telegram_chat_id TEXT,
                    display_name TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tg_v2_queue_status ON telegram_v2_outbound_queue(status, next_retry_at, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tg_v2_mappings_user ON telegram_v2_sender_mappings(username, active)")

    def enqueue(
        self,
        *,
        username: str,
        chat_id: str,
        payload: Dict[str, Any],
        channel: str = "telegram",
    ) -> TelegramOutboundMessage:
        now = utc_now_iso()
        message = TelegramOutboundMessage(
            username=username,
            chat_id=str(chat_id),
            channel=channel or "telegram",
            payload_json=payload or {},
            created_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_v2_outbound_queue (
                    message_id, username, chat_id, channel, payload_json,
                    status, attempt_count, next_retry_at, last_error,
                    created_at, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.username,
                    message.chat_id,
                    message.channel,
                    json.dumps(message.payload_json, ensure_ascii=False, sort_keys=True),
                    message.status,
                    message.attempt_count,
                    message.next_retry_at,
                    message.last_error,
                    message.created_at,
                    message.sent_at,
                ),
            )
        return message

    def get_message(self, message_id: str) -> Optional[TelegramOutboundMessage]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_v2_outbound_queue WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        return self._row_to_message(row) if row else None

    def list_messages(self, *, status: Optional[str] = None, limit: int = 100) -> List[TelegramOutboundMessage]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(max(1, min(int(limit or 100), 500)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM telegram_v2_outbound_queue
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def mark_sent(self, message_id: str) -> Optional[TelegramOutboundMessage]:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE telegram_v2_outbound_queue
                SET status = 'sent', sent_at = ?, last_error = '', next_retry_at = NULL
                WHERE message_id = ?
                """,
                (utc_now_iso(), message_id),
            )
        return self.get_message(message_id)

    def mark_failure(
        self,
        message_id: str,
        *,
        error: str,
        max_attempts: int = 3,
        retry_delay_seconds: int = 60,
    ) -> Optional[TelegramOutboundMessage]:
        current = self.get_message(message_id)
        if current is None:
            return None
        attempts = int(current.attempt_count or 0) + 1
        status = "dead" if attempts >= max(1, int(max_attempts or 3)) else "retry"
        next_retry_at = None
        if status == "retry":
            next_retry_at = (
                datetime.now(timezone.utc) + timedelta(seconds=max(1, int(retry_delay_seconds or 60)))
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE telegram_v2_outbound_queue
                SET status = ?, attempt_count = ?, next_retry_at = ?, last_error = ?
                WHERE message_id = ?
                """,
                (status, attempts, next_retry_at, str(error or "")[:2000], message_id),
            )
        return self.get_message(message_id)

    def reset_for_retry(self, message_id: str) -> Optional[TelegramOutboundMessage]:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE telegram_v2_outbound_queue
                SET status = 'pending', next_retry_at = NULL, last_error = ''
                WHERE message_id = ?
                """,
                (message_id,),
            )
        return self.get_message(message_id)

    def counts(self) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM telegram_v2_outbound_queue GROUP BY status"
            ).fetchall()
        counts = {"pending": 0, "retry": 0, "sent": 0, "dead": 0, "total": 0}
        for row in rows:
            status = str(row["status"] or "")
            count = int(row["count"] or 0)
            counts[status] = count
            counts["total"] += count
        return counts

    def upsert_mapping(self, payload: TelegramSenderMappingRequest) -> TelegramSenderMapping:
        now = utc_now_iso()
        mapping_id = new_id("tgmap")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_v2_sender_mappings (
                    mapping_id, telegram_user_id, username, telegram_chat_id,
                    display_name, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    username = excluded.username,
                    telegram_chat_id = excluded.telegram_chat_id,
                    display_name = excluded.display_name,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    mapping_id,
                    payload.telegram_user_id,
                    payload.username,
                    payload.telegram_chat_id,
                    payload.display_name,
                    1 if payload.active else 0,
                    now,
                    now,
                ),
            )
        mapping = self.get_mapping(payload.telegram_user_id)
        if mapping is None:
            raise RuntimeError("telegram sender mapping was not persisted")
        return mapping

    def get_mapping(self, telegram_user_id: str) -> Optional[TelegramSenderMapping]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_v2_sender_mappings WHERE telegram_user_id = ?",
                (str(telegram_user_id),),
            ).fetchone()
        return self._row_to_mapping(row) if row else None

    def list_mappings(self) -> List[TelegramSenderMapping]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM telegram_v2_sender_mappings ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_mapping(row) for row in rows]

    def active_mapping_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM telegram_v2_sender_mappings WHERE active = 1"
            ).fetchone()
        return int(row[0] or 0)

    def _row_to_message(self, row: sqlite3.Row) -> TelegramOutboundMessage:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        return TelegramOutboundMessage(
            message_id=row["message_id"],
            username=row["username"],
            chat_id=row["chat_id"],
            channel=row["channel"],
            payload_json=payload if isinstance(payload, dict) else {"value": payload},
            status=row["status"],
            attempt_count=int(row["attempt_count"] or 0),
            next_retry_at=row["next_retry_at"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            sent_at=row["sent_at"],
        )

    def _row_to_mapping(self, row: sqlite3.Row) -> TelegramSenderMapping:
        return TelegramSenderMapping(
            mapping_id=row["mapping_id"],
            telegram_user_id=row["telegram_user_id"],
            username=row["username"],
            telegram_chat_id=row["telegram_chat_id"],
            display_name=row["display_name"],
            active=bool(row["active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
