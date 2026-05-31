#!/usr/bin/env python3
"""
Reclassify legacy `consultant` chat history into `advisor` when content indicates
PhD/forensic-AI research context.

Safe by default:
- Creates SQLite backup file before apply
- Supports dry-run mode
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

DB_PATH = Path("/home/kuro/projects/kuro-command-center/kuro_chat_history.db")

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


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def is_advisor_turn(text: str) -> bool:
    haystack = normalize(text)
    return any(re.search(pattern, haystack) for pattern in ADVISOR_PATTERNS)


def chunk_turns(rows: List[sqlite3.Row]) -> List[List[sqlite3.Row]]:
    """Build user-led turns to keep user+assistant rows aligned to one persona."""
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


def build_updates(turns: Iterable[List[sqlite3.Row]]) -> List[Tuple[str, int]]:
    updates: List[Tuple[str, int]] = []
    for turn in turns:
        turn_text = "\n".join((r["content"] or "") for r in turn)
        target = "advisor" if is_advisor_turn(turn_text) else "consultant"
        for row in turn:
            if row["persona"] != target:
                updates.append((target, row["id"]))
    return updates


def backup_db(db_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_suffix(f".db.backup_{ts}")
    shutil.copy2(db_path, backup)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclassify consultant/advisor persona history.")
    parser.add_argument("--apply", action="store_true", help="Apply updates (default is dry-run).")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
    turns = chunk_turns(rows)
    updates = build_updates(turns)

    advisor_count = sum(1 for target, _ in updates if target == "advisor")
    consultant_count = sum(1 for target, _ in updates if target == "consultant")
    print(f"Rows scanned: {len(rows)}")
    print(f"Turns scanned: {len(turns)}")
    print(f"Rows to advisor: {advisor_count}")
    print(f"Rows to consultant: {consultant_count}")
    print(f"Total row updates: {len(updates)}")

    if not args.apply:
        print("Dry-run complete. Re-run with --apply to execute updates.")
        conn.close()
        return 0

    backup = backup_db(DB_PATH)
    print(f"Backup created: {backup}")

    cur.executemany("UPDATE chat_history SET persona = ? WHERE id = ?", updates)
    conn.commit()

    cur.execute("SELECT persona, COUNT(*) AS count FROM chat_history GROUP BY persona ORDER BY count DESC")
    final_counts = cur.fetchall()
    print("Final persona counts:")
    for row in final_counts:
        print(f"- {row['persona']}: {row['count']}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

