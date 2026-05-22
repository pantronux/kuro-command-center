"""SQLite-backed Memory V3 source-of-truth store."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from kuro_backend.config import settings
from kuro_backend.memory_v3.schemas import (
    MemoryConflict,
    MemoryEvent,
    MemoryItem,
    utc_now_iso,
)
from kuro_backend.storage.connection import StorageConnectionManager


def default_memory_v3_db_path() -> str:
    configured = os.getenv("KURO_MEMORY_V3_DB_PATH", "").strip()
    if configured:
        return configured
    return str(Path(getattr(settings, "WORKING_DIR", "") or ".").expanduser() / "kuro_memory_v3.db")


class MemoryV3Store:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or default_memory_v3_db_path())
        self.connection_manager = StorageConnectionManager(self.db_path)

    @property
    def resolved_path(self) -> Path:
        return self.connection_manager.resolved_path

    def init_db(self) -> None:
        with self.connection_manager.transaction() as conn:
            self._create_schema(conn)
            self._seed_retention_policies(conn)

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        return self.connection_manager.connect(read_only=read_only)

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                workspace_id TEXT NOT NULL,
                username TEXT NOT NULL,
                runtime_id TEXT NOT NULL,
                persona_scope TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                trace_id TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS memory_items (
                memory_id TEXT PRIMARY KEY,
                canonical_key TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','deprecated','conflicted','expired','redacted')),
                content TEXT NOT NULL,
                normalized_summary TEXT NOT NULL DEFAULT '',
                confidence_score REAL NOT NULL DEFAULT 0.75,
                importance_score REAL NOT NULL DEFAULT 0.5,
                sensitivity_level TEXT NOT NULL DEFAULT 'low',
                workspace_id TEXT NOT NULL,
                username TEXT NOT NULL,
                runtime_id TEXT NOT NULL,
                persona_scope TEXT NOT NULL,
                chat_id_nullable TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                source_event_id TEXT NOT NULL,
                provenance_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS memory_assertions (
                assertion_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                qualifiers_json TEXT NOT NULL DEFAULT '{}',
                confidence_score REAL NOT NULL DEFAULT 0.75,
                evidence_refs_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS memory_links (
                link_id TEXT PRIMARY KEY,
                source_memory_id TEXT NOT NULL,
                target_memory_id TEXT NOT NULL,
                link_type TEXT NOT NULL,
                confidence_score REAL NOT NULL DEFAULT 0.75
            );

            CREATE TABLE IF NOT EXISTS memory_conflicts (
                conflict_id TEXT PRIMARY KEY,
                memory_id_a TEXT NOT NULL,
                memory_id_b TEXT NOT NULL,
                conflict_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                resolution_strategy TEXT DEFAULT '',
                resolution_notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS memory_access_log (
                access_id TEXT PRIMARY KEY,
                access_type TEXT NOT NULL
                    CHECK (access_type IN ('read','write','update','delete','redact')),
                memory_id_nullable TEXT,
                query_hash_nullable TEXT,
                workspace_id TEXT NOT NULL,
                username TEXT NOT NULL,
                runtime_id TEXT NOT NULL,
                chat_id_nullable TEXT,
                trace_id TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_retention_policies (
                policy_id TEXT PRIMARY KEY,
                memory_type TEXT NOT NULL UNIQUE,
                retention_days INTEGER,
                action TEXT NOT NULL DEFAULT 'expire',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_redaction_log (
                redaction_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                actor_username TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_embedding_refs (
                ref_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                vector_store TEXT NOT NULL,
                external_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_source_refs (
                ref_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_uri TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memory_events_scope
                ON memory_events(workspace_id, username, runtime_id, persona_scope, chat_id);
            CREATE INDEX IF NOT EXISTS idx_memory_items_scope
                ON memory_items(workspace_id, username, runtime_id, persona_scope, chat_id_nullable, status);
            CREATE INDEX IF NOT EXISTS idx_memory_items_canonical
                ON memory_items(workspace_id, username, runtime_id, persona_scope, canonical_key);
            CREATE INDEX IF NOT EXISTS idx_memory_items_expiry
                ON memory_items(status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_memory_access_scope
                ON memory_access_log(workspace_id, username, runtime_id, chat_id_nullable, created_at);
            CREATE INDEX IF NOT EXISTS idx_memory_conflicts_status
                ON memory_conflicts(status, created_at);
            """
        )

    @staticmethod
    def _seed_retention_policies(conn: sqlite3.Connection) -> None:
        policies = [
            ("ephemeral_context", 1),
            ("working_memory", 30),
            ("episodic_memory", 365),
            ("semantic_memory", None),
            ("procedural_memory", None),
            ("operational_memory", 180),
            ("evidence_memory", 2555),
            ("reflective_memory", 365),
            ("task_memory", 90),
            ("market_signal_memory", 30),
            ("user_preference_memory", None),
            ("system_policy_memory", None),
        ]
        now = utc_now_iso()
        for memory_type, days in policies:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_retention_policies
                    (policy_id, memory_type, retention_days, action, created_at)
                VALUES (?, ?, ?, 'expire', ?)
                """,
                (f"policy_{memory_type}", memory_type, days, now),
            )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> MemoryEvent:
        return MemoryEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            idempotency_key=row["idempotency_key"],
            workspace_id=row["workspace_id"],
            username=row["username"],
            runtime_id=row["runtime_id"],
            persona_scope=row["persona_scope"],
            chat_id=row["chat_id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            payload_json=json.loads(row["payload_json"] or "{}"),
            created_at=row["created_at"],
            trace_id=row["trace_id"] or "",
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            memory_id=row["memory_id"],
            canonical_key=row["canonical_key"],
            memory_type=row["memory_type"],
            status=row["status"],
            content=row["content"],
            normalized_summary=row["normalized_summary"] or "",
            confidence_score=float(row["confidence_score"]),
            importance_score=float(row["importance_score"]),
            sensitivity_level=row["sensitivity_level"],
            workspace_id=row["workspace_id"],
            username=row["username"],
            runtime_id=row["runtime_id"],
            persona_scope=row["persona_scope"],
            chat_id_nullable=row["chat_id_nullable"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            source_event_id=row["source_event_id"],
            provenance_json=json.loads(row["provenance_json"] or "{}"),
        )

    def append_event(self, event: MemoryEvent) -> MemoryEvent:
        self.init_db()
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_events (
                    event_id, event_type, idempotency_key, workspace_id, username,
                    runtime_id, persona_scope, chat_id, source_type, source_id,
                    payload_json, created_at, trace_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.idempotency_key,
                    event.workspace_id,
                    event.username,
                    event.runtime_id,
                    event.persona_scope,
                    event.chat_id,
                    event.source_type,
                    event.source_id,
                    json.dumps(event.payload_json, ensure_ascii=False, sort_keys=True),
                    event.created_at,
                    event.trace_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM memory_events WHERE idempotency_key = ?",
                (event.idempotency_key,),
            ).fetchone()
        return self._event_from_row(row)

    def get_event_by_idempotency_key(self, idempotency_key: str) -> Optional[MemoryEvent]:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM memory_events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return self._event_from_row(row) if row else None

    def get_memory_item_by_event(self, event_id: str) -> Optional[MemoryItem]:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE source_event_id = ?",
                (event_id,),
            ).fetchone()
        return self._item_from_row(row) if row else None

    def upsert_memory_item(self, item: MemoryItem) -> str:
        self.init_db()
        now = utc_now_iso()
        item.updated_at = now
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                    memory_id, canonical_key, memory_type, status, content,
                    normalized_summary, confidence_score, importance_score,
                    sensitivity_level, workspace_id, username, runtime_id,
                    persona_scope, chat_id_nullable, created_at, updated_at,
                    expires_at, source_event_id, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    canonical_key=excluded.canonical_key,
                    memory_type=excluded.memory_type,
                    status=excluded.status,
                    content=excluded.content,
                    normalized_summary=excluded.normalized_summary,
                    confidence_score=excluded.confidence_score,
                    importance_score=excluded.importance_score,
                    sensitivity_level=excluded.sensitivity_level,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at,
                    provenance_json=excluded.provenance_json
                """,
                (
                    item.memory_id,
                    item.canonical_key,
                    item.memory_type,
                    item.status,
                    item.content,
                    item.normalized_summary,
                    item.confidence_score,
                    item.importance_score,
                    item.sensitivity_level,
                    item.workspace_id,
                    item.username,
                    item.runtime_id,
                    item.persona_scope,
                    item.chat_id_nullable,
                    item.created_at,
                    item.updated_at,
                    item.expires_at,
                    item.source_event_id,
                    json.dumps(item.provenance_json, ensure_ascii=False, sort_keys=True),
                ),
            )
        return item.memory_id

    def get_memory_item(
        self,
        memory_id: str,
        *,
        workspace_id: str | None = None,
        username: str | None = None,
        runtime_id: str | None = None,
        chat_id: str | None = None,
    ) -> Optional[MemoryItem]:
        self.init_db()
        query = ["SELECT * FROM memory_items WHERE memory_id = ?"]
        params: List[Any] = [memory_id]
        if workspace_id:
            query.append("AND workspace_id = ?")
            params.append(workspace_id)
        if username:
            query.append("AND username = ?")
            params.append(username)
        if runtime_id:
            query.append("AND runtime_id = ?")
            params.append(runtime_id)
        if chat_id:
            query.append("AND chat_id_nullable = ?")
            params.append(chat_id)
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(" ".join(query), tuple(params)).fetchone()
        return self._item_from_row(row) if row else None

    def find_by_canonical_key(
        self,
        *,
        canonical_key: str,
        workspace_id: str,
        username: str,
        runtime_id: str,
        persona_scope: str,
        chat_id: str | None = None,
        limit: int = 20,
    ) -> List[MemoryItem]:
        self.init_db()
        query = [
            "SELECT * FROM memory_items",
            "WHERE canonical_key = ?",
            "AND workspace_id = ? AND username = ? AND runtime_id = ? AND persona_scope = ?",
            "AND status != 'redacted'",
        ]
        params: List[Any] = [canonical_key, workspace_id, username, runtime_id, persona_scope]
        if chat_id is not None:
            query.append("AND chat_id_nullable = ?")
            params.append(chat_id)
        query.append("ORDER BY updated_at DESC LIMIT ?")
        params.append(limit)
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(" ".join(query), tuple(params)).fetchall()
        return [self._item_from_row(row) for row in rows]

    def search_memory_items_basic(
        self,
        *,
        workspace_id: str,
        username: str,
        runtime_id: str,
        persona_scope: str,
        query_text: str = "",
        memory_type: str | None = None,
        chat_id: str | None = None,
        include_cross_chat: bool = False,
        limit: int = 20,
    ) -> List[MemoryItem]:
        self.init_db()
        query = [
            "SELECT * FROM memory_items",
            "WHERE workspace_id = ? AND username = ? AND runtime_id = ? AND persona_scope = ?",
            "AND status = 'active'",
            "AND (expires_at IS NULL OR replace(expires_at, 'T', ' ') > datetime('now'))",
        ]
        params: List[Any] = [workspace_id, username, runtime_id, persona_scope]
        if memory_type:
            query.append("AND memory_type = ?")
            params.append(memory_type)
        if chat_id and not include_cross_chat:
            query.append("AND chat_id_nullable = ?")
            params.append(chat_id)
        if query_text:
            like = f"%{query_text.strip()}%"
            query.append(
                "AND (content LIKE ? OR normalized_summary LIKE ? OR canonical_key LIKE ?)"
            )
            params.extend([like, like, like])
        query.append("ORDER BY importance_score DESC, confidence_score DESC, updated_at DESC LIMIT ?")
        params.append(max(1, int(limit)))
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(" ".join(query), tuple(params)).fetchall()
        return [self._item_from_row(row) for row in rows]

    def log_access(
        self,
        *,
        access_type: str,
        workspace_id: str,
        username: str,
        runtime_id: str,
        chat_id: str | None = None,
        memory_id: str | None = None,
        query_hash: str | None = None,
        trace_id: str = "",
    ) -> None:
        self.init_db()
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                INSERT INTO memory_access_log (
                    access_id, access_type, memory_id_nullable, query_hash_nullable,
                    workspace_id, username, runtime_id, chat_id_nullable, trace_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"macc_{os.urandom(12).hex()}",
                    access_type,
                    memory_id,
                    query_hash,
                    workspace_id,
                    username,
                    runtime_id,
                    chat_id,
                    trace_id,
                    utc_now_iso(),
                ),
            )

    def list_access_log(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_access_log
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_expired(self, *, now: str | None = None) -> int:
        self.init_db()
        now_value = now or utc_now_iso()
        with self.connection_manager.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE memory_items
                SET status = 'expired', updated_at = ?
                WHERE status = 'active'
                  AND expires_at IS NOT NULL
                  AND replace(expires_at, 'T', ' ') <= replace(?, 'T', ' ')
                """,
                (now_value, now_value),
            )
            return int(cur.rowcount or 0)

    def redact_memory(self, memory_id: str, *, actor_username: str, reason: str) -> bool:
        self.init_db()
        now = utc_now_iso()
        with self.connection_manager.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE memory_items
                SET status = 'redacted',
                    content = '[redacted]',
                    normalized_summary = '',
                    updated_at = ?,
                    provenance_json = ?
                WHERE memory_id = ?
                """,
                (now, json.dumps({"redacted": True, "reason": reason}, sort_keys=True), memory_id),
            )
            changed = int(cur.rowcount or 0) > 0
            if changed:
                conn.execute(
                    """
                    INSERT INTO memory_redaction_log
                        (redaction_id, memory_id, actor_username, reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (f"mred_{os.urandom(12).hex()}", memory_id, actor_username, reason, now),
                )
        if changed:
            item = self.get_memory_item(memory_id)
            if item:
                self.log_access(
                    access_type="redact",
                    workspace_id=item.workspace_id,
                    username=item.username,
                    runtime_id=item.runtime_id,
                    chat_id=item.chat_id_nullable,
                    memory_id=memory_id,
                )
        return changed

    def create_conflict(
        self,
        *,
        memory_id_a: str,
        memory_id_b: str,
        conflict_type: str = "contradiction",
        resolution_strategy: str = "",
    ) -> MemoryConflict:
        self.init_db()
        conflict = MemoryConflict(
            memory_id_a=memory_id_a,
            memory_id_b=memory_id_b,
            conflict_type=conflict_type,
            resolution_strategy=resolution_strategy,
        )
        with self.connection_manager.transaction() as conn:
            conn.execute(
                """
                INSERT INTO memory_conflicts (
                    conflict_id, memory_id_a, memory_id_b, conflict_type, status,
                    resolution_strategy, resolution_notes, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conflict.conflict_id,
                    conflict.memory_id_a,
                    conflict.memory_id_b,
                    conflict.conflict_type,
                    conflict.status,
                    conflict.resolution_strategy,
                    conflict.resolution_notes,
                    conflict.created_at,
                    conflict.resolved_at,
                ),
            )
            conn.execute(
                "UPDATE memory_items SET status = 'conflicted', updated_at = ? WHERE memory_id IN (?, ?)",
                (utc_now_iso(), memory_id_a, memory_id_b),
            )
        return conflict

    def list_conflicts(self, *, status: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
        self.init_db()
        query = ["SELECT * FROM memory_conflicts"]
        params: List[Any] = []
        if status:
            query.append("WHERE status = ?")
            params.append(status)
        query.append("ORDER BY created_at DESC LIMIT ?")
        params.append(max(1, min(500, int(limit))))
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(" ".join(query), tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def resolve_conflict(
        self,
        conflict_id: str,
        *,
        resolution_strategy: str,
        resolution_notes: str = "",
    ) -> bool:
        self.init_db()
        with self.connection_manager.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE memory_conflicts
                SET status = 'resolved',
                    resolution_strategy = ?,
                    resolution_notes = ?,
                    resolved_at = ?
                WHERE conflict_id = ?
                """,
                (resolution_strategy, resolution_notes, utc_now_iso(), conflict_id),
            )
        return int(cur.rowcount or 0) > 0

    def count_rows(self, table: str) -> int:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            row = conn.execute(f'SELECT COUNT(*) AS count FROM "{table}"').fetchone()
        return int(row["count"] if row else 0)

    def table_names(self) -> List[str]:
        self.init_db()
        with self.connection_manager.transaction(read_only=True) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        return [str(row["name"]) for row in rows]
