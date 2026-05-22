"""Adapters for bridging legacy memory stores into Memory V3 events."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from kuro_backend.memory_v3.schemas import MemoryWriteRequest
from kuro_backend.memory_v3.writer import MemoryWriter


def _rows_from_sqlite(db_path: str | Path, sql: str, params: Iterable[Any]) -> List[Dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


class LegacyShortTermAdapter:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path

    def _path(self) -> str:
        if self.db_path:
            return str(self.db_path)
        from kuro_backend import memory_manager

        return memory_manager.SHORT_TERM_DB

    def read_recent(
        self,
        *,
        username: str,
        runtime_id: str | None = None,
        chat_id: str | None = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM short_term WHERE username = ?"
        params: list[Any] = [username]
        if runtime_id:
            sql += " AND COALESCE(runtime_id, 'sovereign') = ?"
            params.append(runtime_id)
        if chat_id:
            sql += " AND chat_id = ?"
            params.append(chat_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        return _rows_from_sqlite(self._path(), sql, params)


class ChatHistoryAdapter:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path

    def _path(self) -> str:
        if self.db_path:
            return str(self.db_path)
        from kuro_backend import chat_history

        return chat_history.DB_PATH

    def read_recent(self, *, username: str, chat_id: str | None = None, limit: int = 20) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM chat_history WHERE username = ?"
        params: list[Any] = [username]
        if chat_id:
            sql += " AND chat_id = ?"
            params.append(chat_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        return _rows_from_sqlite(self._path(), sql, params)


class ResearchLedgerAdapter:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path

    def _path(self) -> str:
        if self.db_path:
            return str(self.db_path)
        from kuro_backend import memory_manager

        return memory_manager.SHORT_TERM_DB

    def read_recent(self, *, username: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = _rows_from_sqlite(
            self._path(),
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'research_ledger'",
            (),
        )
        if not rows:
            return []
        return _rows_from_sqlite(
            self._path(),
            "SELECT * FROM research_ledger WHERE username = ? ORDER BY created_at DESC LIMIT ?",
            (username, limit),
        )


class Mem0Adapter:
    """Bridge already-fetched Mem0 records into Memory V3 without calling Mem0."""

    def bridge_records(
        self,
        records: Iterable[Dict[str, Any]],
        *,
        writer: MemoryWriter,
        workspace_id: str,
        username: str,
        runtime_id: str,
        persona_scope: str,
        chat_id: str,
    ) -> list[str]:
        memory_ids: list[str] = []
        for record in records:
            content = str(record.get("memory") or record.get("content") or "").strip()
            if not content:
                continue
            result = writer.write(
                MemoryWriteRequest(
                    workspace_id=workspace_id,
                    username=username,
                    runtime_id=runtime_id,
                    persona_scope=persona_scope,
                    chat_id=chat_id,
                    source_type="mem0",
                    source_id=str(record.get("id") or record.get("memory_id") or content[:64]),
                    content=content,
                    memory_type="semantic_memory",
                    metadata={"mem0_metadata": record.get("metadata") or {}},
                )
            )
            memory_ids.append(result.memory_id)
        return memory_ids


class IngestionAdapter:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path

    def _path(self) -> str:
        if self.db_path:
            return str(self.db_path)
        from kuro_backend.ingestion_center import ingestion_registry

        return ingestion_registry.DB_PATH

    def read_datasets(self, *, username: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = _rows_from_sqlite(
            self._path(),
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ingestion_datasets'",
            (),
        )
        if not rows:
            return []
        return _rows_from_sqlite(
            self._path(),
            "SELECT * FROM ingestion_datasets WHERE owner_username = ? ORDER BY created_at DESC LIMIT ?",
            (username, limit),
        )


def serialize_bridge_payload(row: Dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)
