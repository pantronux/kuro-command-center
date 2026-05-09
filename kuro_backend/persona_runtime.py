from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from kuro_backend import memory_manager


_DEFAULT_STATE = {
    "formality": 0.55,
    "verbosity": 0.50,
    "challenge_level": 0.50,
    "interaction_depth": 0.50,
}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(memory_manager.SHORT_TERM_DB)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> None:
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS persona_runtime_state (
                username TEXT NOT NULL,
                session_id TEXT NOT NULL,
                formality REAL NOT NULL DEFAULT 0.55,
                verbosity REAL NOT NULL DEFAULT 0.50,
                challenge_level REAL NOT NULL DEFAULT 0.50,
                interaction_depth REAL NOT NULL DEFAULT 0.50,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (username, session_id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_runtime_state(username: str, session_id: str) -> Dict[str, float]:
    ensure_schema()
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT formality, verbosity, challenge_level, interaction_depth FROM persona_runtime_state WHERE username = ? AND session_id = ?",
            (username, session_id),
        )
        row = c.fetchone()
    finally:
        conn.close()
    if row is None:
        return dict(_DEFAULT_STATE)
    return {
        "formality": float(row["formality"]),
        "verbosity": float(row["verbosity"]),
        "challenge_level": float(row["challenge_level"]),
        "interaction_depth": float(row["interaction_depth"]),
    }


def upsert_runtime_state(username: str, session_id: str, **updates: Any) -> None:
    ensure_schema()
    current = get_runtime_state(username, session_id)
    merged = {**current, **{k: float(v) for k, v in updates.items() if k in current and v is not None}}
    conn = _conn()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO persona_runtime_state (
                username, session_id, formality, verbosity, challenge_level, interaction_depth
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, session_id) DO UPDATE SET
                formality = excluded.formality,
                verbosity = excluded.verbosity,
                challenge_level = excluded.challenge_level,
                interaction_depth = excluded.interaction_depth,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                username,
                session_id,
                merged["formality"],
                merged["verbosity"],
                merged["challenge_level"],
                merged["interaction_depth"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def build_runtime_hint(username: str, session_id: Optional[str]) -> str:
    if not session_id:
        return ""
    s = get_runtime_state(username, session_id)
    return (
        "\n\n[PERSONA_RUNTIME_STATE]\n"
        f"- formality={s['formality']:.2f}\n"
        f"- verbosity={s['verbosity']:.2f}\n"
        f"- challenge_level={s['challenge_level']:.2f}\n"
        f"- interaction_depth={s['interaction_depth']:.2f}\n"
        "Use this only for tone adaptation, not for exposing internal metadata."
    )
