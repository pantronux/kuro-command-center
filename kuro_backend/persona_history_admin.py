"""
Admin utilities for persona-specific chat history maintenance.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from kuro_backend.config import settings
from kuro_backend import memory_manager

DB_PATH = Path(settings.WORKING_DIR) / "kuro_chat_history.db"
BACKUP_GLOB = "kuro_chat_history.db.backup_*"

# Strong research/forensic indicators -> advisor
ADVISOR_PATTERNS = [
    r"\bphd\b",
    r"\bs3\b",
    r"digital forensics?",
    r"forensic",
    r"novelty",
    r"counter[- ]?evidence",
    r"socratic",
    r"chain of custody",
    r"eu ai act",
    r"nist ai 100-2",
    r"adversarial",
    r"model inversion",
    r"prompt injection",
    r"explainab|xai|lime|shap",
    r"data provenance|data poisoning|poisoning",
    r"metodolog",
    r"proposal disertasi|sidang proposal|tesis|disertasi",
]

_ADVISOR_REGEX = [re.compile(pattern) for pattern in ADVISOR_PATTERNS]


@dataclass
class _TurnSummary:
    row_ids: List[int]
    target: str
    excerpt: str


def _get_conn(path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _is_advisor_turn(text: str) -> bool:
    haystack = _normalize_text(text)
    return any(regex.search(haystack) for regex in _ADVISOR_REGEX)


def _chunk_turns(rows: Sequence[sqlite3.Row]) -> List[List[sqlite3.Row]]:
    turns: List[List[sqlite3.Row]] = []
    current: List[sqlite3.Row] = []
    for row in rows:
        role = (row["role"] or "").lower()
        if role == "user" and current:
            turns.append(current)
            current = [row]
        else:
            current.append(row)
    if current:
        turns.append(current)
    return turns


def _build_turn_summaries(turns: Iterable[List[sqlite3.Row]]) -> List[_TurnSummary]:
    summaries: List[_TurnSummary] = []
    for turn in turns:
        turn_text = "\n".join((row["content"] or "") for row in turn)
        target = "advisor" if _is_advisor_turn(turn_text) else "consultant"
        row_ids = [int(row["id"]) for row in turn]
        excerpt = (turn_text[:220] + "...") if len(turn_text) > 220 else turn_text
        summaries.append(_TurnSummary(row_ids=row_ids, target=target, excerpt=excerpt))
    return summaries


def get_persona_counts() -> Dict[str, int]:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT persona, COUNT(*) AS count FROM chat_history GROUP BY persona ORDER BY count DESC")
        return {str(row["persona"]): int(row["count"]) for row in cur.fetchall()}
    finally:
        conn.close()


def list_backups(limit: int = 20) -> List[str]:
    files = sorted(Path(settings.WORKING_DIR).glob(BACKUP_GLOB), reverse=True)
    return [f.name for f in files[: max(1, limit)]]


def preview_reclassify(limit_turns: int = 30) -> Dict:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, role, content, persona
            FROM chat_history
            WHERE persona IN ('consultant', 'advisor')
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
        turns = _chunk_turns(rows)
        summaries = _build_turn_summaries(turns)

        updates: List[Tuple[str, int]] = []
        for summary, turn in zip(summaries, turns):
            for row in turn:
                if row["persona"] != summary.target:
                    updates.append((summary.target, int(row["id"])))

        advisor_count = sum(1 for target, _ in updates if target == "advisor")
        consultant_count = sum(1 for target, _ in updates if target == "consultant")
        sample = [
            {
                "row_ids": summary.row_ids,
                "target": summary.target,
                "excerpt": summary.excerpt,
            }
            for summary in summaries[: max(1, limit_turns)]
        ]
        return {
            "rows_scanned": len(rows),
            "turns_scanned": len(turns),
            "updates_total": len(updates),
            "updates_to_advisor": advisor_count,
            "updates_to_consultant": consultant_count,
            "sample_turns": sample,
        }
    finally:
        conn.close()


def run_reclassify(apply_changes: bool = False) -> Dict:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, role, content, persona
            FROM chat_history
            WHERE persona IN ('consultant', 'advisor')
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
        turns = _chunk_turns(rows)
        summaries = _build_turn_summaries(turns)

        updates: List[Tuple[str, int]] = []
        for summary, turn in zip(summaries, turns):
            for row in turn:
                if row["persona"] != summary.target:
                    updates.append((summary.target, int(row["id"])))

        result = {
            "rows_scanned": len(rows),
            "turns_scanned": len(turns),
            "updates_total": len(updates),
            "updates_to_advisor": sum(1 for target, _ in updates if target == "advisor"),
            "updates_to_consultant": sum(1 for target, _ in updates if target == "consultant"),
            "applied": False,
        }
        if not apply_changes:
            return result

        if updates:
            cur.executemany("UPDATE chat_history SET persona = ? WHERE id = ?", updates)
            conn.commit()
        result["applied"] = True
        result["counts_after"] = get_persona_counts()
        return result
    finally:
        conn.close()


def override_persona(row_ids: Sequence[int], persona: str) -> Dict:
    normalized = memory_manager.normalize_persona(persona)
    if normalized not in memory_manager.CANONICAL_PERSONAS:
        raise ValueError(f"Invalid persona: {persona}")
    ids = [int(x) for x in row_ids if str(x).strip()]
    if not ids:
        return {"updated_rows": 0, "persona": normalized}
    conn = _get_conn()
    try:
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ids)
        cur.execute(
            f"UPDATE chat_history SET persona = ? WHERE id IN ({placeholders})",
            (normalized, *ids),
        )
        conn.commit()
        return {"updated_rows": int(cur.rowcount), "persona": normalized}
    finally:
        conn.close()


def restore_persona_from_backup(backup_file: str) -> Dict:
    backup_path = Path(settings.WORKING_DIR) / backup_file
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")

    current = _get_conn()
    backup = _get_conn(backup_path)
    try:
        bcur = backup.cursor()
        bcur.execute("SELECT id, persona FROM chat_history")
        rows = bcur.fetchall()
        updates = [(str(row["persona"]), int(row["id"])) for row in rows]

        ccur = current.cursor()
        ccur.executemany("UPDATE chat_history SET persona = ? WHERE id = ?", updates)
        current.commit()

        return {
            "restored_rows": len(updates),
            "backup_file": backup_file,
            "restored_at": datetime.now().isoformat(),
            "counts_after": get_persona_counts(),
        }
    finally:
        backup.close()
        current.close()

