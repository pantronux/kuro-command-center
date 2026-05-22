"""Clean Reminders V2 store."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from kuro_backend.tools_v2.audit import utc_now_iso
from kuro_backend.tools_v2.schemas import tools_v2_db_path


REMINDER_STATUSES = {"scheduled", "sent", "cancelled", "failed"}


class ReminderStore:
    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else tools_v2_db_path()
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
                CREATE TABLE IF NOT EXISTS reminders_v2 (
                    reminder_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    username TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    channel TEXT NOT NULL DEFAULT 'web',
                    remind_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_v2_user ON reminders_v2(username, workspace_id, status)")

    def create_reminder(
        self,
        *,
        username: str,
        workspace_id: str = "default",
        remind_at: str,
        task_id: Optional[str] = None,
        channel: str = "web",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = utc_now_iso()
        reminder_id = f"rem_{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reminders_v2 (
                    reminder_id, task_id, username, workspace_id, channel,
                    remind_at, status, attempt_count, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'scheduled', 0, ?, ?)
                """,
                (
                    reminder_id,
                    task_id,
                    username,
                    workspace_id or "default",
                    channel if channel in {"web", "telegram", "both"} else "web",
                    remind_at,
                    now,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
        reminder = self.get_reminder(reminder_id=reminder_id, username=username)
        if reminder is None:
            raise RuntimeError("reminder was not persisted")
        return reminder

    def get_reminder(self, *, reminder_id: str, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reminders_v2 WHERE reminder_id = ? AND username = ?",
                (reminder_id, username),
            ).fetchone()
        return self._row_to_reminder(row) if row else None

    def list_reminders(
        self,
        *,
        username: str,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses = ["username = ?"]
        params: list[Any] = [username]
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(max(1, min(int(limit or 100), 500)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM reminders_v2
                WHERE {' AND '.join(clauses)}
                ORDER BY remind_at ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def update_reminder(self, *, reminder_id: str, username: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        allowed = {"remind_at", "channel", "status", "attempt_count", "last_error", "metadata"}
        updates = {key: value for key, value in (patch or {}).items() if key in allowed and value is not None}
        if not updates:
            return self.get_reminder(reminder_id=reminder_id, username=username)
        if self.get_reminder(reminder_id=reminder_id, username=username) is None:
            return None
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in updates.items():
            if key == "metadata":
                assignments.append("metadata_json = ?")
                params.append(json.dumps(value or {}, ensure_ascii=False, sort_keys=True))
            elif key == "status":
                status = str(value or "").strip()
                if status not in REMINDER_STATUSES:
                    raise ValueError("invalid reminder status")
                assignments.append("status = ?")
                params.append(status)
                if status == "sent":
                    assignments.append("sent_at = ?")
                    params.append(utc_now_iso())
            elif key == "channel":
                channel = str(value or "web").strip()
                if channel not in {"web", "telegram", "both"}:
                    raise ValueError("invalid reminder channel")
                assignments.append("channel = ?")
                params.append(channel)
            else:
                assignments.append(f"{key} = ?")
                params.append(value)
        params.extend([reminder_id, username])
        with self._connect() as conn:
            conn.execute(
                f"UPDATE reminders_v2 SET {', '.join(assignments)} WHERE reminder_id = ? AND username = ?",
                tuple(params),
            )
        return self.get_reminder(reminder_id=reminder_id, username=username)

    def _row_to_reminder(self, row: sqlite3.Row) -> Dict[str, Any]:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            metadata = {}
        return {
            "reminder_id": row["reminder_id"],
            "task_id": row["task_id"],
            "username": row["username"],
            "workspace_id": row["workspace_id"],
            "channel": row["channel"],
            "remind_at": row["remind_at"],
            "status": row["status"],
            "attempt_count": int(row["attempt_count"] or 0),
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "sent_at": row["sent_at"],
            "metadata": metadata if isinstance(metadata, dict) else {"value": metadata},
        }
