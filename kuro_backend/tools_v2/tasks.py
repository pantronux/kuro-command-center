"""Clean Tasks V2 store."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from kuro_backend.tools_v2.audit import utc_now_iso
from kuro_backend.tools_v2.schemas import tools_v2_db_path


TASK_STATUSES = {"open", "in_progress", "completed", "cancelled", "deleted"}


class TaskStore:
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
                CREATE TABLE IF NOT EXISTS tasks_v2 (
                    task_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    due_at TEXT,
                    recurrence_rule TEXT,
                    source_chat_id TEXT,
                    source_message_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_v2_user ON tasks_v2(username, workspace_id, status)")

    def create_task(
        self,
        *,
        username: str,
        workspace_id: str = "default",
        title: str,
        description: str = "",
        due_at: Optional[str] = None,
        recurrence_rule: Optional[str] = None,
        source_chat_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = utc_now_iso()
        task_id = f"task_{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks_v2 (
                    task_id, username, workspace_id, title, description, status,
                    due_at, recurrence_rule, source_chat_id, source_message_id,
                    created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    username,
                    workspace_id or "default",
                    title.strip(),
                    description or "",
                    due_at,
                    recurrence_rule,
                    source_chat_id,
                    source_message_id,
                    now,
                    now,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
        task = self.get_task(task_id=task_id, username=username)
        if task is None:
            raise RuntimeError("task was not persisted")
        return task

    def get_task(self, *, task_id: str, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks_v2 WHERE task_id = ? AND username = ? AND status != 'deleted'",
                (task_id, username),
            ).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(
        self,
        *,
        username: str,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses = ["username = ?", "status != 'deleted'"]
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
                SELECT * FROM tasks_v2
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def update_task(self, *, task_id: str, username: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        allowed = {"title", "description", "status", "due_at", "recurrence_rule", "metadata"}
        updates: Dict[str, Any] = {key: value for key, value in (patch or {}).items() if key in allowed and value is not None}
        if not updates:
            return self.get_task(task_id=task_id, username=username)
        current = self.get_task(task_id=task_id, username=username)
        if current is None:
            return None
        assignments: list[str] = []
        params: list[Any] = []
        now = utc_now_iso()
        for key, value in updates.items():
            if key == "metadata":
                assignments.append("metadata_json = ?")
                params.append(json.dumps(value or {}, ensure_ascii=False, sort_keys=True))
            elif key == "status":
                status = str(value or "").strip()
                if status not in TASK_STATUSES:
                    raise ValueError("invalid task status")
                assignments.append("status = ?")
                params.append(status)
                if status == "completed":
                    assignments.append("completed_at = ?")
                    params.append(now)
            else:
                assignments.append(f"{key} = ?")
                params.append(str(value).strip() if isinstance(value, str) else value)
        assignments.append("updated_at = ?")
        params.append(now)
        params.extend([task_id, username])
        with self._connect() as conn:
            conn.execute(
                f"UPDATE tasks_v2 SET {', '.join(assignments)} WHERE task_id = ? AND username = ?",
                tuple(params),
            )
        return self.get_task(task_id=task_id, username=username)

    def delete_task(self, *, task_id: str, username: str) -> bool:
        now = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks_v2
                SET status = 'deleted', updated_at = ?
                WHERE task_id = ? AND username = ? AND status != 'deleted'
                """,
                (now, task_id, username),
            )
            return cursor.rowcount > 0

    def _row_to_task(self, row: sqlite3.Row) -> Dict[str, Any]:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            metadata = {}
        return {
            "task_id": row["task_id"],
            "username": row["username"],
            "workspace_id": row["workspace_id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "due_at": row["due_at"],
            "recurrence_rule": row["recurrence_rule"],
            "source_chat_id": row["source_chat_id"],
            "source_message_id": row["source_message_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "metadata": metadata if isinstance(metadata, dict) else {"value": metadata},
        }
