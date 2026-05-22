"""Memory V2 store abstraction and persistence layer."""

# --- Header Doc ---
# Purpose: Runtime/namespace-aware memory store with provenance metadata.
# Caller: decay_engine.py, qa_runtime.py, tests.
# Dependencies: memory_manager.py, db_utils.py, migrations.py.
# Main Functions: MemoryStore.add(), retrieve(), expire(), mark_conflicted().
# Side Effects: Persists rows in `kuro_short_term.db` table `short_term`.

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from kuro_backend.db_utils import get_connection

logger = logging.getLogger(__name__)


def _utc_now_sql() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _require_username(username: Optional[str]) -> str:
    value = str(username or "").strip()
    if not value:
        raise ValueError("username is required for MemoryStore operations")
    return value


class MemoryProvenance(BaseModel):
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    document_id: Optional[str] = None
    tool_call_id: Optional[str] = None


class KuroMemory(BaseModel):
    id: str = Field(default_factory=lambda: f"mem_{uuid.uuid4().hex}")
    runtime_id: str
    namespace: str
    type: Literal[
        "short_term",
        "working",
        "episodic",
        "semantic",
        "operational",
        "reflective",
    ]
    content: str
    source: str = "conversation"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: MemoryProvenance = Field(default_factory=MemoryProvenance)
    created_at: str = Field(default_factory=_utc_now_sql)
    updated_at: str = Field(default_factory=_utc_now_sql)
    expires_at: Optional[str] = None
    status: Literal["active", "expired", "conflicted", "deprecated"] = "active"
    username: str = ""


class MemoryStore:
    """SQLite-backed store for KuroMemory rows."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path
        self._ensure_schema()

    def _resolve_db_path(self) -> str:
        if self._db_path:
            return self._db_path
        from kuro_backend import memory_manager

        return memory_manager.SHORT_TERM_DB

    def _conn(self):
        conn = get_connection(self._resolve_db_path())
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        db_path = self._resolve_db_path()
        if not self._db_path:
            from kuro_backend import memory_manager

            memory_manager.init_short_term_db()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = self._conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS short_term (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    persona_scope TEXT NOT NULL DEFAULT 'consultant',
                    username TEXT NOT NULL DEFAULT 'Pantronux',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    chat_id TEXT DEFAULT NULL
                )
                """
            )
            from kuro_backend.memory_v2.migrations import extend_short_term_schema

            extend_short_term_schema(conn)
        finally:
            conn.close()

    @staticmethod
    def _row_to_memory(row) -> KuroMemory:
        provenance_raw = row["provenance_json"] if "provenance_json" in row.keys() else "{}"
        try:
            provenance_obj = json.loads(provenance_raw or "{}")
            if not isinstance(provenance_obj, dict):
                provenance_obj = {}
        except Exception:
            provenance_obj = {}
        created_at = str(row["timestamp"] or _utc_now_sql())
        return KuroMemory(
            id=str(row["memory_id"] or f"mem_legacy_{row['id']}"),
            runtime_id=str(row["runtime_id"] or "sovereign"),
            namespace=str(row["namespace"] or "kuro.sovereign"),
            type=str(row["memory_type"] or "short_term"),  # type: ignore[arg-type]
            content=str(row["content"] or ""),
            source=str(row["source"] or "conversation"),
            confidence=float(row["confidence"] if row["confidence"] is not None else 1.0),
            provenance=MemoryProvenance(**provenance_obj),
            created_at=created_at,
            updated_at=created_at,
            expires_at=(str(row["expires_at"]) if row["expires_at"] else None),
            status=str(row["status"] or "active"),  # type: ignore[arg-type]
            username=str(row["username"] or ""),
        )

    def add(self, memory: KuroMemory) -> str:
        username = _require_username(memory.username)
        from kuro_backend.memory_v2.provenance_tracker import normalize_provenance

        provenance = normalize_provenance(memory.provenance)
        existing_conflicts: list[KuroMemory] = []
        if memory.type in ("semantic", "episodic"):
            try:
                from kuro_backend.memory_v2.conflict_resolver import detect_conflicts

                existing = self.retrieve(
                    namespace=memory.namespace,
                    runtime_id=memory.runtime_id,
                    memory_type=memory.type,
                    username=username,
                    limit=50,
                )
                existing_conflicts = detect_conflicts(memory, existing)
            except Exception as exc:
                logger.warning("Memory conflict detection skipped: %s", exc)
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO short_term (
                    role, content, persona_scope, username, chat_id,
                    memory_id, runtime_id, namespace, memory_type, confidence,
                    provenance_json, expires_at, status, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "assistant",
                    memory.content,
                    "consultant",
                    username,
                    provenance.session_id,
                    memory.id,
                    memory.runtime_id,
                    memory.namespace,
                    memory.type,
                    float(memory.confidence),
                    provenance.model_dump_json(),
                    memory.expires_at,
                    memory.status,
                    memory.source,
                ),
            )
            conn.commit()
            if existing_conflicts:
                from kuro_backend.memory_v2.conflict_resolver import resolve_conflict

                resolve_conflict(self, memory, existing_conflicts)
            return memory.id
        finally:
            conn.close()

    def retrieve(
        self,
        namespace: str,
        runtime_id: str,
        username: str,
        memory_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[KuroMemory]:
        username = _require_username(username)
        conn = self._conn()
        try:
            query = [
                "SELECT * FROM short_term",
                "WHERE status = 'active'",
                "AND namespace = ?",
                "AND runtime_id = ?",
                "AND (expires_at IS NULL OR replace(expires_at, 'T', ' ') > datetime('now'))",
            ]
            params: list[object] = [namespace, runtime_id]
            if memory_type:
                query.append("AND memory_type = ?")
                params.append(memory_type)
            query.append("AND username = ?")
            params.append(username)
            query.append("ORDER BY confidence DESC, id DESC LIMIT ?")
            params.append(max(1, int(limit)))
            rows = conn.execute(" ".join(query), params).fetchall()
            return [self._row_to_memory(row) for row in rows]
        finally:
            conn.close()

    def expire(self, memory_id: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE short_term SET status = 'expired' WHERE memory_id = ?",
                (memory_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_conflicted(self, memory_id: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE short_term SET status = 'conflicted' WHERE memory_id = ?",
                (memory_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def get_by_id(self, memory_id: str) -> Optional[KuroMemory]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM short_term WHERE memory_id = ? LIMIT 1",
                (memory_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_memory(row)
        finally:
            conn.close()

    def retrieve_all_active_without_expiry(self) -> list[KuroMemory]:
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM short_term
                WHERE status = 'active'
                  AND expires_at IS NULL
                ORDER BY id DESC
                """
            ).fetchall()
            return [self._row_to_memory(row) for row in rows]
        finally:
            conn.close()

    def iter_active_without_expiry(self, batch_size: int = 500):
        last_row_id = 0
        size = max(1, int(batch_size or 500))
        while True:
            conn = self._conn()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM short_term
                    WHERE status = 'active'
                      AND expires_at IS NULL
                      AND id > ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (last_row_id, size),
                ).fetchall()
            finally:
                conn.close()
            if not rows:
                break
            for row in rows:
                last_row_id = int(row["id"])
                yield self._row_to_memory(row)

    def retrieve_stale(self, as_of: str) -> list[KuroMemory]:
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM short_term
                WHERE status = 'active'
                  AND expires_at IS NOT NULL
                  AND replace(expires_at, 'T', ' ') < replace(?, 'T', ' ')
                ORDER BY id DESC
                """,
                (as_of,),
            ).fetchall()
            return [self._row_to_memory(row) for row in rows]
        finally:
            conn.close()

    def iter_stale(self, as_of: str, batch_size: int = 500):
        last_row_id = 0
        size = max(1, int(batch_size or 500))
        while True:
            conn = self._conn()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM short_term
                    WHERE status = 'active'
                      AND expires_at IS NOT NULL
                      AND replace(expires_at, 'T', ' ') < replace(?, 'T', ' ')
                      AND id > ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (as_of, last_row_id, size),
                ).fetchall()
            finally:
                conn.close()
            if not rows:
                break
            for row in rows:
                last_row_id = int(row["id"])
                yield self._row_to_memory(row)

    def set_expires_at(self, memory_id: str, expires_at: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE short_term SET expires_at = ? WHERE memory_id = ?",
                (expires_at, memory_id),
            )
            conn.commit()
        finally:
            conn.close()

    def set_expires_at_many(self, updates: list[tuple[str, str]]) -> None:
        if not updates:
            return
        conn = self._conn()
        try:
            conn.executemany(
                "UPDATE short_term SET expires_at = ? WHERE memory_id = ?",
                [(expires_at, memory_id) for memory_id, expires_at in updates],
            )
            conn.commit()
        finally:
            conn.close()

    def expire_many(self, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        conn = self._conn()
        try:
            conn.executemany(
                "UPDATE short_term SET status = 'expired' WHERE memory_id = ?",
                [(memory_id,) for memory_id in memory_ids],
            )
            conn.commit()
        finally:
            conn.close()
