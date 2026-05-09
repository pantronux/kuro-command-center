from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from kuro_backend.config import settings

logger = logging.getLogger(__name__)
logger.propagate = False

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "kuro_ingestion.db")
_SCHEMA_READY_FOR: Optional[str] = None
_SCHEMA_LOCK = threading.Lock()


def _reset_schema_ready_for_tests() -> None:
    global _SCHEMA_READY_FOR
    with _SCHEMA_LOCK:
        _SCHEMA_READY_FOR = None


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    global _SCHEMA_READY_FOR
    current_path = DB_PATH
    if _SCHEMA_READY_FOR == current_path:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY_FOR == current_path:
            return
        _init_db_locked()
        _SCHEMA_READY_FOR = current_path


def _init_db_locked() -> None:
    conn = None
    try:
        try:
            from kuro_backend import backup_manager

            backup_manager.snapshot_pre_migration(DB_PATH, label="ingestion")
        except Exception as exc:
            logger.warning("Pre-migration snapshot skipped: %s", exc)

        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ingested_datasets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_uuid TEXT UNIQUE NOT NULL,
                dataset_name TEXT NOT NULL,
                original_filename TEXT,
                file_path TEXT,
                file_hash_sha256 TEXT,
                source_type TEXT,
                category TEXT,
                owner_username TEXT,
                ingestion_status TEXT,
                chunk_count INTEGER DEFAULT 0,
                embedding_count INTEGER DEFAULT 0,
                vector_collection TEXT,
                memory_scope TEXT,
                tags_json TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT,
                deleted_at TEXT,
                last_error TEXT,
                parser_type TEXT,
                entity_count INTEGER DEFAULT 0,
                summary_text TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_uuid TEXT NOT NULL,
                chunk_index INTEGER,
                chunk_text TEXT,
                chunk_hash TEXT,
                token_count INTEGER,
                embedding_status TEXT,
                retrieval_count INTEGER DEFAULT 0,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                entity_json TEXT DEFAULT '[]',
                preview_text TEXT DEFAULT '',
                vector_id TEXT,
                is_orphan INTEGER DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_uuid TEXT,
                username TEXT,
                job_type TEXT,
                status TEXT,
                progress_percent INTEGER DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT,
                logs_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS retrieval_analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_uuid TEXT,
                chunk_id INTEGER,
                retrieval_source TEXT,
                retrieval_score REAL,
                hallucination_flag INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                chat_id TEXT,
                username TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_lineage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_uuid TEXT,
                parent_dataset_uuid TEXT,
                operation_type TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        index_sql = (
            "CREATE INDEX IF NOT EXISTS idx_ingested_dataset_uuid ON ingested_datasets(dataset_uuid)",
            "CREATE INDEX IF NOT EXISTS idx_ingested_owner_created ON ingested_datasets(owner_username, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_ingested_status ON ingested_datasets(ingestion_status)",
            "CREATE INDEX IF NOT EXISTS idx_ingested_category ON ingested_datasets(category)",
            "CREATE INDEX IF NOT EXISTS idx_dataset_chunks_dataset_idx ON dataset_chunks(dataset_uuid, chunk_index)",
            "CREATE INDEX IF NOT EXISTS idx_dataset_chunks_hash ON dataset_chunks(chunk_hash)",
            "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_dataset_created ON ingestion_jobs(dataset_uuid, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status_created ON ingestion_jobs(status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_retrieval_analytics_dataset_created ON retrieval_analytics(dataset_uuid, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dataset_lineage_dataset_created ON dataset_lineage(dataset_uuid, created_at DESC)",
        )
        for sql in index_sql:
            cur.execute(sql)
        conn.commit()
    finally:
        if conn:
            conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    init_db()
    conn = _get_connection()
    try:
        conn.execute(sql, tuple(params))
        conn.commit()
    finally:
        conn.close()


def fetch_one(sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
    init_db()
    conn = _get_connection()
    try:
        row = conn.execute(sql, tuple(params)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def fetch_all(sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    init_db()
    conn = _get_connection()
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_dataset(payload: Dict[str, Any]) -> Dict[str, Any]:
    init_db()
    now = now_iso()
    data = {
        "dataset_uuid": payload["dataset_uuid"],
        "dataset_name": payload["dataset_name"],
        "original_filename": payload.get("original_filename", ""),
        "file_path": payload.get("file_path"),
        "file_hash_sha256": payload.get("file_hash_sha256", ""),
        "source_type": payload.get("source_type", ""),
        "category": payload.get("category", ""),
        "owner_username": payload.get("owner_username", ""),
        "ingestion_status": payload.get("ingestion_status", "queued"),
        "chunk_count": payload.get("chunk_count", 0),
        "embedding_count": payload.get("embedding_count", 0),
        "vector_collection": payload.get("vector_collection", ""),
        "memory_scope": payload.get("memory_scope", ""),
        "tags_json": json.dumps(payload.get("tags", []), ensure_ascii=False),
        "metadata_json": json.dumps(payload.get("metadata", {}), ensure_ascii=False),
        "created_at": payload.get("created_at", now),
        "updated_at": payload.get("updated_at", now),
        "archived_at": payload.get("archived_at"),
        "deleted_at": payload.get("deleted_at"),
        "last_error": payload.get("last_error"),
        "parser_type": payload.get("parser_type"),
        "entity_count": payload.get("entity_count", 0),
        "summary_text": payload.get("summary_text"),
    }
    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT INTO ingested_datasets (
                dataset_uuid, dataset_name, original_filename, file_path, file_hash_sha256,
                source_type, category, owner_username, ingestion_status, chunk_count,
                embedding_count, vector_collection, memory_scope, tags_json, metadata_json,
                created_at, updated_at, archived_at, deleted_at, last_error, parser_type,
                entity_count, summary_text
            ) VALUES (
                :dataset_uuid, :dataset_name, :original_filename, :file_path, :file_hash_sha256,
                :source_type, :category, :owner_username, :ingestion_status, :chunk_count,
                :embedding_count, :vector_collection, :memory_scope, :tags_json, :metadata_json,
                :created_at, :updated_at, :archived_at, :deleted_at, :last_error, :parser_type,
                :entity_count, :summary_text
            )
            """,
            data,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ingested_datasets WHERE dataset_uuid = ?",
            (data["dataset_uuid"],),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_dataset(dataset_uuid: str, **updates: Any) -> Optional[Dict[str, Any]]:
    if not updates:
        return get_dataset(dataset_uuid)
    updates["updated_at"] = now_iso()
    columns = ", ".join(f"{key} = ?" for key in updates.keys())
    params = list(updates.values()) + [dataset_uuid]
    execute(f"UPDATE ingested_datasets SET {columns} WHERE dataset_uuid = ?", params)
    return get_dataset(dataset_uuid)


def get_dataset(dataset_uuid: str) -> Optional[Dict[str, Any]]:
    return fetch_one("SELECT * FROM ingested_datasets WHERE dataset_uuid = ?", (dataset_uuid,))


def find_dataset_by_hash(owner_username: str, sha256_hash: str) -> Optional[Dict[str, Any]]:
    return fetch_one(
        """
        SELECT * FROM ingested_datasets
        WHERE owner_username = ? AND file_hash_sha256 = ? AND deleted_at IS NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        (owner_username, sha256_hash),
    )


def list_datasets(owner_username: Optional[str] = None, active_only: bool = False) -> List[Dict[str, Any]]:
    clauses = []
    params: List[Any] = []
    if owner_username:
        clauses.append("owner_username = ?")
        params.append(owner_username)
    if active_only:
        clauses.append("ingestion_status NOT IN ('archived', 'deleted')")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return fetch_all(f"SELECT * FROM ingested_datasets {where} ORDER BY created_at DESC", params)


def list_active_datasets(
    owner_username: str,
    allowed_statuses: tuple[str, ...] = ("completed", "partially_indexed"),
) -> List[Dict[str, Any]]:
    if not allowed_statuses:
        return []
    placeholders = ",".join("?" for _ in allowed_statuses)
    params: List[Any] = [owner_username, *allowed_statuses]
    return fetch_all(
        f"""
        SELECT * FROM ingested_datasets
        WHERE owner_username = ?
          AND archived_at IS NULL
          AND deleted_at IS NULL
          AND ingestion_status IN ({placeholders})
        ORDER BY created_at DESC
        """,
        params,
    )


def replace_chunks(dataset_uuid: str, chunks: List[Dict[str, Any]]) -> int:
    init_db()
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM dataset_chunks WHERE dataset_uuid = ?", (dataset_uuid,))
        conn.executemany(
            """
            INSERT INTO dataset_chunks (
                dataset_uuid, chunk_index, chunk_text, chunk_hash, token_count,
                embedding_status, retrieval_count, metadata_json, created_at,
                entity_json, preview_text, vector_id, is_orphan
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    dataset_uuid,
                    chunk["chunk_index"],
                    chunk["chunk_text"],
                    chunk["chunk_hash"],
                    chunk["token_count"],
                    chunk.get("embedding_status", "queued"),
                    chunk.get("retrieval_count", 0),
                    json.dumps(chunk.get("metadata", {}), ensure_ascii=False),
                    chunk.get("created_at", now_iso()),
                    json.dumps(chunk.get("entities", []), ensure_ascii=False),
                    chunk.get("preview_text", ""),
                    chunk.get("vector_id"),
                    chunk.get("is_orphan", 0),
                )
                for chunk in chunks
            ],
        )
        conn.commit()
        return len(chunks)
    finally:
        conn.close()


def list_chunks(dataset_uuid: str) -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM dataset_chunks WHERE dataset_uuid = ? ORDER BY chunk_index ASC", (dataset_uuid,))


def get_chunk_by_dataset_and_index(dataset_uuid: str, chunk_index: int) -> Optional[Dict[str, Any]]:
    return fetch_one(
        "SELECT * FROM dataset_chunks WHERE dataset_uuid = ? AND chunk_index = ? LIMIT 1",
        (dataset_uuid, chunk_index),
    )


def increment_chunk_retrieval_count(chunk_id: int, amount: int = 1) -> None:
    execute(
        "UPDATE dataset_chunks SET retrieval_count = COALESCE(retrieval_count, 0) + ? WHERE id = ?",
        (max(1, int(amount)), chunk_id),
    )


def update_chunk_vector(dataset_uuid: str, chunk_index: int, vector_id: Optional[str], embedding_status: str) -> None:
    execute(
        """
        UPDATE dataset_chunks
        SET vector_id = ?, embedding_status = ?, is_orphan = CASE WHEN ? IS NULL THEN 1 ELSE 0 END
        WHERE dataset_uuid = ? AND chunk_index = ?
        """,
        (vector_id, embedding_status, vector_id, dataset_uuid, chunk_index),
    )


def update_chunk_orphans(dataset_uuid: str, vector_ids_missing: Iterable[str]) -> int:
    missing = {v for v in vector_ids_missing if v}
    chunks = list_chunks(dataset_uuid)
    count = 0
    for chunk in chunks:
        is_orphan = 1 if chunk.get("vector_id") in missing else 0
        if int(chunk.get("is_orphan", 0)) != is_orphan:
            execute(
                "UPDATE dataset_chunks SET is_orphan = ? WHERE id = ?",
                (is_orphan, chunk["id"]),
            )
            count += 1
    return count


def create_job(dataset_uuid: Optional[str], username: str, job_type: str, status: str = "queued") -> Dict[str, Any]:
    init_db()
    stamp = now_iso()
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ingestion_jobs (
                dataset_uuid, username, job_type, status, progress_percent,
                started_at, completed_at, error_message, logs_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, NULL, NULL, NULL, '[]', ?, ?)
            """,
            (dataset_uuid, username, job_type, status, stamp, stamp),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_job(job_id: int, **updates: Any) -> Optional[Dict[str, Any]]:
    if not updates:
        return get_job(job_id)
    updates["updated_at"] = now_iso()
    columns = ", ".join(f"{key} = ?" for key in updates.keys())
    params = list(updates.values()) + [job_id]
    execute(f"UPDATE ingestion_jobs SET {columns} WHERE id = ?", params)
    return get_job(job_id)


def append_job_log(job_id: int, message: str) -> Optional[Dict[str, Any]]:
    job = get_job(job_id)
    if job is None:
        return None
    logs = json.loads(job.get("logs_json") or "[]")
    logs.append({"ts": now_iso(), "message": message})
    return update_job(job_id, logs_json=json.dumps(logs, ensure_ascii=False))


def get_job(job_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,))


def list_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM ingestion_jobs ORDER BY created_at DESC LIMIT ?", (limit,))


def create_lineage(dataset_uuid: str, operation_type: str, metadata: Dict[str, Any], parent_dataset_uuid: Optional[str] = None) -> None:
    execute(
        """
        INSERT INTO dataset_lineage (
            dataset_uuid, parent_dataset_uuid, operation_type, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (dataset_uuid, parent_dataset_uuid, operation_type, json.dumps(metadata, ensure_ascii=False), now_iso()),
    )


def list_lineage(dataset_uuid: str) -> List[Dict[str, Any]]:
    return fetch_all(
        "SELECT * FROM dataset_lineage WHERE dataset_uuid = ? ORDER BY created_at DESC, id DESC",
        (dataset_uuid,),
    )


def create_retrieval_event(payload: Dict[str, Any]) -> None:
    execute(
        """
        INSERT INTO retrieval_analytics (
            dataset_uuid, chunk_id, retrieval_source, retrieval_score, hallucination_flag,
            created_at, chat_id, username
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.get("dataset_uuid"),
            payload.get("chunk_id"),
            payload.get("retrieval_source", ""),
            payload.get("retrieval_score", 0.0),
            payload.get("hallucination_flag", 0),
            payload.get("created_at", now_iso()),
            payload.get("chat_id"),
            payload.get("username", ""),
        ),
    )


def list_retrieval_events(limit: int = 200) -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM retrieval_analytics ORDER BY created_at DESC LIMIT ?", (limit,))


def get_retrieval_summary(limit: int = 10) -> List[Dict[str, Any]]:
    return fetch_all(
        """
        SELECT dataset_uuid, COUNT(*) AS retrieval_count,
               AVG(retrieval_score) AS avg_score,
               SUM(CASE WHEN hallucination_flag = 1 THEN 1 ELSE 0 END) AS hallucination_count
        FROM retrieval_analytics
        GROUP BY dataset_uuid
        ORDER BY retrieval_count DESC, avg_score DESC
        LIMIT ?
        """,
        (limit,),
    )


def search_datasets(query: str, owner_username: Optional[str] = None) -> List[Dict[str, Any]]:
    like_query = f"%{query.strip()}%"
    sql = """
        SELECT d.*, c.preview_text AS matched_chunk_preview
        FROM ingested_datasets d
        LEFT JOIN dataset_chunks c ON c.dataset_uuid = d.dataset_uuid
        WHERE (
            d.dataset_name LIKE ? OR
            d.original_filename LIKE ? OR
            d.tags_json LIKE ? OR
            c.preview_text LIKE ?
        )
    """
    params: List[Any] = [like_query, like_query, like_query, like_query]
    if owner_username:
        sql += " AND d.owner_username = ?"
        params.append(owner_username)
    sql += " ORDER BY d.created_at DESC"
    return fetch_all(sql, params)


def get_status_counts() -> Dict[str, int]:
    rows = fetch_all(
        """
        SELECT ingestion_status, COUNT(*) AS count
        FROM ingested_datasets
        GROUP BY ingestion_status
        """
    )
    return {row["ingestion_status"]: row["count"] for row in rows}


def get_totals() -> Dict[str, Any]:
    row = fetch_one(
        """
        SELECT COUNT(*) AS dataset_count,
               COALESCE(SUM(chunk_count), 0) AS chunk_count,
               COALESCE(SUM(embedding_count), 0) AS embedding_count
        FROM ingested_datasets
        WHERE deleted_at IS NULL
        """
    ) or {"dataset_count": 0, "chunk_count": 0, "embedding_count": 0}
    row["status_counts"] = get_status_counts()
    return row
