"""
Kuro AI — Joint Goal Store (T3 Shared Agency)
===============================================
Persistent SQLite-backed store for joint commitments between Kuro and Master Pantronux.
Survives process restarts — research-PhD commitments span weeks/months, not sessions.

Schema: joint_goals(id, description, chapter_ref, status, created_at)
         stored in kuro_short_term.db alongside memory_manager tables.

--- Header Doc ---
Purpose: CRUD for joint dissertation commitments (T3 Shared Agency tier).
Caller: metacognitive_review_node, response_node, main.py /api/agency/* (future routes).
Dependencies: sqlite3, os (KURO_SHORT_TERM_DB env var).
Main Functions: add_commitment(), get_active_commitments(), format_for_prompt(), close_commitment(), search_commitments().
Side Effects: SQLite writes/reads to kuro_short_term.db joint_goals table.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
logger.propagate = False

# Resolve DB path the same way memory_manager.py does so all short-term tables
# end up in the same file.
_DB_PATH = os.getenv("KURO_SHORT_TERM_DB", "kuro_short_term.db")
_SCHEMA_READY = False
_SCHEMA_LOCK_OBJ = None

import threading
_SCHEMA_LOCK = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, timeout=8, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_joint_goals_table() -> None:
    """Idempotent DDL bootstrap — safe to call multiple times."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        try:
            with _conn() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS joint_goals (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        description TEXT    NOT NULL,
                        chapter_ref TEXT    DEFAULT '',
                        status      TEXT    DEFAULT 'active',
                        created_at  TEXT    DEFAULT (datetime('now')),
                        closed_at   TEXT    DEFAULT NULL
                    )
                """)
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_joint_goals_status "
                    "ON joint_goals(status)"
                )
                c.commit()
            _SCHEMA_READY = True
            logger.info("[JOINT_GOAL] Table initialised at %s", _DB_PATH)
        except Exception as exc:
            logger.error("[JOINT_GOAL] Schema init failed: %s", exc)


def add_commitment(description: str, chapter_ref: str = "") -> int:
    """
    Add a new active joint commitment.

    Args:
        description: Human-readable commitment text.
                     e.g. "Bab 1 fokus pada novelty AI forensics dalam konteks UU PDP"
        chapter_ref: Optional chapter/section reference.
                     e.g. "Bab 3, Section 3.2"
    Returns:
        Inserted row id (int).
    """
    init_joint_goals_table()
    try:
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO joint_goals (description, chapter_ref) VALUES (?, ?)",
                (description.strip(), chapter_ref.strip()),
            )
            c.commit()
            row_id = cur.lastrowid
            logger.info("[JOINT_GOAL] Added commitment id=%s: %s", row_id, description[:80])
            return row_id
    except Exception as exc:
        logger.error("[JOINT_GOAL] add_commitment failed: %s", exc)
        return -1


def get_active_commitments(limit: int = 15) -> List[Dict]:
    """Return all active commitments ordered newest-first."""
    try:
        init_joint_goals_table()
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM joint_goals WHERE status='active' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("[JOINT_GOAL] get_active_commitments failed: %s", exc)
        return []


def get_all_commitments(limit: int = 30) -> List[Dict]:
    """Return all commitments (active + closed) for admin/review."""
    try:
        init_joint_goals_table()
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM joint_goals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("[JOINT_GOAL] get_all_commitments failed: %s", exc)
        return []


def search_commitments(keyword: str) -> List[Dict]:
    """Full-text keyword search over active commitments."""
    try:
        init_joint_goals_table()
        pattern = f"%{keyword.strip()}%"
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM joint_goals WHERE status='active' "
                "AND (description LIKE ? OR chapter_ref LIKE ?) "
                "ORDER BY created_at DESC LIMIT 10",
                (pattern, pattern),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("[JOINT_GOAL] search_commitments failed: %s", exc)
        return []


def close_commitment(goal_id: int) -> bool:
    """Mark a commitment as closed (completed/superseded)."""
    try:
        init_joint_goals_table()
        with _conn() as c:
            c.execute(
                "UPDATE joint_goals SET status='closed', closed_at=datetime('now') WHERE id=?",
                (goal_id,),
            )
            c.commit()
        logger.info("[JOINT_GOAL] Closed commitment id=%s", goal_id)
        return True
    except Exception as exc:
        logger.warning("[JOINT_GOAL] close_commitment failed id=%s: %s", goal_id, exc)
        return False


def format_for_prompt() -> str:
    """
    Format active commitments as a prompt-injection block.

    Returns empty string when no commitments exist (safe to inject unconditionally).
    """
    goals = get_active_commitments(limit=10)
    if not goals:
        return ""
    lines = [
        "[JOINT_COMMITMENTS — Joint Commitment with Master Pantronux]",
        "Proactively reference this commitment when relevant:",
    ]
    for g in goals:
        ref = f" ({g['chapter_ref']})" if g.get("chapter_ref") else ""
        ts = (g.get("created_at") or "")[:10]  # YYYY-MM-DD only
        lines.append(f"  • [{ts}]{ref} {g['description']}")
    return "\n".join(lines)
