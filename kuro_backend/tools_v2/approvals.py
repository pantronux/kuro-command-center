"""Approval request store for governed tool execution."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from kuro_backend.tools_v2.audit import utc_now_iso
from kuro_backend.tools_v2.schemas import ToolApprovalRequest, ToolDefinition, tools_v2_db_path


class ToolApprovalStore:
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
                CREATE TABLE IF NOT EXISTS tool_approval_requests_v2 (
                    approval_id TEXT PRIMARY KEY,
                    tool_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    expires_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_approval_v2_status ON tool_approval_requests_v2(status, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_approval_v2_user ON tool_approval_requests_v2(username, created_at)")

    def create_request(
        self,
        *,
        definition: ToolDefinition,
        username: str,
        runtime_id: str,
        workspace_id: str,
        input_payload: Dict[str, Any],
        reason: str,
        ttl_seconds: int = 900,
    ) -> ToolApprovalRequest:
        approval_id = f"tap_{uuid.uuid4().hex}"
        created_at = utc_now_iso()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=max(60, int(ttl_seconds or 900)))
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_approval_requests_v2 (
                    approval_id, tool_id, username, runtime_id, workspace_id,
                    risk_level, reason, status, input_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    approval_id,
                    definition.tool_id,
                    username,
                    runtime_id,
                    workspace_id,
                    definition.risk_level,
                    reason,
                    json.dumps(input_payload or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                    expires_at,
                ),
            )
        created = self.get(approval_id)
        if created is None:
            raise RuntimeError("approval request was not persisted")
        return created

    def get(self, approval_id: Optional[str]) -> Optional[ToolApprovalRequest]:
        if not approval_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_approval_requests_v2 WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        approval = self._row_to_approval(row)
        if approval.status == "pending" and approval.expires_at and approval.expires_at <= utc_now_iso():
            self._set_status(approval.approval_id, "expired", decided_by="system")
            approval = approval.model_copy(update={"status": "expired", "decided_by": "system", "decided_at": utc_now_iso()})
        return approval

    def list_pending(self, *, limit: int = 100) -> List[ToolApprovalRequest]:
        limit = max(1, min(int(limit or 100), 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tool_approval_requests_v2
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_approval(row) for row in rows]

    def approve(self, approval_id: str, *, decided_by: str) -> Optional[ToolApprovalRequest]:
        self._set_status(approval_id, "approved", decided_by=decided_by)
        return self.get(approval_id)

    def deny(self, approval_id: str, *, decided_by: str) -> Optional[ToolApprovalRequest]:
        self._set_status(approval_id, "denied", decided_by=decided_by)
        return self.get(approval_id)

    def is_approved_for(self, approval_id: Optional[str], *, tool_id: str, username: str) -> bool:
        approval = self.get(approval_id)
        return bool(
            approval
            and approval.status == "approved"
            and approval.tool_id == tool_id
            and approval.username == username
        )

    def _set_status(self, approval_id: str, status: str, *, decided_by: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tool_approval_requests_v2
                SET status = ?, decided_at = ?, decided_by = ?
                WHERE approval_id = ?
                """,
                (status, utc_now_iso(), decided_by, approval_id),
            )

    def _row_to_approval(self, row: sqlite3.Row) -> ToolApprovalRequest:
        try:
            input_payload = json.loads(row["input_json"] or "{}")
        except Exception:
            input_payload = {}
        return ToolApprovalRequest(
            approval_id=row["approval_id"],
            tool_id=row["tool_id"],
            username=row["username"],
            runtime_id=row["runtime_id"],
            workspace_id=row["workspace_id"],
            risk_level=row["risk_level"],
            reason=row["reason"],
            status=row["status"],
            input_json=input_payload if isinstance(input_payload, dict) else {"value": input_payload},
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            expires_at=row["expires_at"],
        )
