"""SQLite audit log for Tool Runtime V2."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from kuro_backend.tools_v2.schemas import ToolAuditEvent, tools_v2_db_path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ToolAuditStore:
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
                CREATE TABLE IF NOT EXISTS tool_audit_log_v2 (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    tool_id TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    runtime_id TEXT NOT NULL DEFAULT '',
                    workspace_id TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    risk_level TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    approval_id TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_v2_tool ON tool_audit_log_v2(tool_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_v2_user ON tool_audit_log_v2(username, created_at)")

    def log_event(
        self,
        *,
        event_type: str,
        tool_id: str = "",
        username: str = "",
        runtime_id: str = "",
        workspace_id: str = "",
        trace_id: str = "",
        risk_level: str = "",
        status: str = "",
        approval_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> int:
        created_at = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tool_audit_log_v2 (
                    event_type, tool_id, username, runtime_id, workspace_id,
                    trace_id, risk_level, status, approval_id, payload_json,
                    error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    tool_id,
                    username,
                    runtime_id,
                    workspace_id,
                    trace_id,
                    risk_level,
                    status,
                    approval_id,
                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                    str(error or "")[:2000],
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def list_events(self, *, limit: int = 100, username: Optional[str] = None) -> List[ToolAuditEvent]:
        limit = max(1, min(int(limit or 100), 500))
        params: list[Any] = []
        where = ""
        if username:
            where = "WHERE username = ?"
            params.append(username)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM tool_audit_log_v2
                {where}
                ORDER BY audit_id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _row_to_event(self, row: sqlite3.Row) -> ToolAuditEvent:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        return ToolAuditEvent(
            audit_id=int(row["audit_id"]),
            event_type=row["event_type"],
            tool_id=row["tool_id"],
            username=row["username"],
            runtime_id=row["runtime_id"],
            workspace_id=row["workspace_id"],
            trace_id=row["trace_id"],
            risk_level=row["risk_level"],
            status=row["status"],
            approval_id=row["approval_id"],
            payload_json=payload if isinstance(payload, dict) else {"value": payload},
            error=row["error"],
            created_at=row["created_at"],
        )
