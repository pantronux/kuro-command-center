"""Idempotency utilities for future write endpoints."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Dict, Optional


def _canonical_body(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body).decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_idempotency_key(
    *,
    route: str,
    user: str,
    body: Any,
    chat_id: Optional[str] = None,
) -> str:
    payload = {
        "route": route or "",
        "user": user or "",
        "chat_id": chat_id or "",
        "body": _canonical_body(body),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_idempotency_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_results (
            idempotency_key TEXT PRIMARY KEY,
            route TEXT NOT NULL,
            user TEXT NOT NULL,
            chat_id TEXT DEFAULT '',
            request_hash TEXT NOT NULL,
            status_code INTEGER NOT NULL DEFAULT 200,
            response_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def persist_idempotency_result(
    conn: sqlite3.Connection,
    *,
    idempotency_key: str,
    route: str,
    user: str,
    request_hash: str,
    response: Dict[str, Any],
    status_code: int = 200,
    chat_id: Optional[str] = None,
) -> None:
    ensure_idempotency_table(conn)
    conn.execute(
        """
        INSERT OR IGNORE INTO idempotency_results
            (idempotency_key, route, user, chat_id, request_hash, status_code, response_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            idempotency_key,
            route,
            user,
            chat_id or "",
            request_hash,
            int(status_code),
            json.dumps(response, sort_keys=True, ensure_ascii=False),
        ),
    )
    conn.commit()


def get_idempotency_result(
    conn: sqlite3.Connection,
    idempotency_key: str,
) -> Optional[Dict[str, Any]]:
    ensure_idempotency_table(conn)
    row = conn.execute(
        """
        SELECT idempotency_key, route, user, chat_id, request_hash,
               status_code, response_json, created_at
        FROM idempotency_results
        WHERE idempotency_key = ?
        """,
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        id_key = row["idempotency_key"]
        route = row["route"]
        user = row["user"]
        chat_id = row["chat_id"]
        request_hash = row["request_hash"]
        status_code = row["status_code"]
        response_json = row["response_json"]
        created_at = row["created_at"]
    else:
        id_key, route, user, chat_id, request_hash, status_code, response_json, created_at = row
    return {
        "idempotency_key": id_key,
        "route": route,
        "user": user,
        "chat_id": chat_id,
        "request_hash": request_hash,
        "status_code": int(status_code),
        "response": json.loads(response_json),
        "created_at": created_at,
    }
