"""
Kuro AI V6.0 Sovereign — kuro_backend.services.core_service — Sync metadata and DB orchestration.

--- Header Doc ---
Purpose: Persisted sync revision management + cross-DB initialization orchestration.
Caller: main.py routes, dreaming_worker, memory_coordinator (revision read).
Dependencies: sqlite3, tools.PROJECT_ROOT, logger.
Main Functions: init_all_databases(), bump_data_revision(), get_data_revision().
Side Effects: Writes to kuro_short_term.db (WAL); bumps cache-buster revision used by semantic_cache.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from kuro_backend.tools import PROJECT_ROOT

logger = logging.getLogger(__name__)
logger.propagate = False

_write_lock = threading.Lock()
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None

SYNC_METADATA_KEY_REVISION = "data_revision"

def _resolve_db_path_with_env(env_var: str, default_filename: str) -> str:
    env_path = os.getenv(env_var)
    if env_path:
        return os.path.abspath(env_path)
    return os.path.join(PROJECT_ROOT, default_filename)

SHORT_TERM_DB_PATH = _resolve_db_path_with_env("KURO_SHORT_TERM_DB_PATH", "kuro_short_term.db")

def _conn_short_term():
    conn = sqlite3.connect(SHORT_TERM_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def register_main_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once from FastAPI startup so bumps can schedule WebSocket broadcasts."""
    global _main_event_loop
    _main_event_loop = loop

def _notify_websocket_refresh(revision: int) -> None:
    loop = _main_event_loop
    if loop is None or not loop.is_running():
        return
    try:
        from kuro_backend import dashboard_broadcast
        asyncio.run_coroutine_threadsafe(
            dashboard_broadcast.broadcast_refresh(revision),
            loop,
        )
    except Exception as e:
        logger.debug("[SYNC] websocket schedule skipped: %s", e)

def bump_data_revision() -> None:
    """Increment persisted revision (short_term DB) so all workers share one counter; then push WS."""
    new_val: int
    with _write_lock:
        conn = _conn_short_term()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS app_sync_metadata ("
                "key TEXT PRIMARY KEY, "
                "value INTEGER, "
                "updated_at DATETIME DEFAULT (datetime('now')))"
            )
            cur.execute(
                "INSERT OR IGNORE INTO app_sync_metadata (key, value) VALUES (?, 0)",
                (SYNC_METADATA_KEY_REVISION,),
            )
            cur.execute(
                "UPDATE app_sync_metadata SET value = value + 1, updated_at = datetime('now') WHERE key = ?",
                (SYNC_METADATA_KEY_REVISION,),
            )
            cur.execute(
                "SELECT value FROM app_sync_metadata WHERE key = ?",
                (SYNC_METADATA_KEY_REVISION,),
            )
            row = cur.fetchone()
            new_val = int(row[0]) if row else 0
            conn.commit()
        finally:
            conn.close()
    logger.info("[SYNC] Revision bumped to %s", new_val)
    _notify_websocket_refresh(new_val)

def get_data_revision() -> int:
    """Current persisted revision (short_term DB). Used by semantic_cache for invalidation."""
    conn = _conn_short_term()
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS app_sync_metadata ("
            "key TEXT PRIMARY KEY, "
            "value INTEGER, "
            "updated_at DATETIME DEFAULT (datetime('now')))"
        )
        cur.execute(
            "SELECT value FROM app_sync_metadata WHERE key = ?",
            (SYNC_METADATA_KEY_REVISION,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        conn.close()

def init_all_databases() -> None:
    logger.info("[DB_PATH] Active SQLite files -> short_term=%s", SHORT_TERM_DB_PATH)
    # Initialize sync table
    get_data_revision()
    
    try:
        from kuro_backend import finance_db
        finance_db.init_db()
    except Exception as exc:
        logger.warning("[DB_PATH] finance_db init skipped: %s", exc)

init_all_databases()
