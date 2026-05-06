#!/usr/bin/env python3
"""
Kuro AI V1.0.0 — One-shot migration: legacy chat_id → Default Chat.

Scans chat_history for rows with chat_id IS NULL or LIKE 'legacy_%',
groups them by (username, persona), creates a "Default Chat" session,
and re-assigns those rows to the Default Chat.

Usage:
    cd /home/kuro/projects/kuro
    python scripts/migrate_chat_id.py [--dry-run]
"""
import os
import sys
import sqlite3
import argparse
from collections import defaultdict

# Ensure kuro_backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kuro_backend.config import settings
from kuro_backend.chat_history import _get_connection  # noqa: E402


def migrate(dry_run: bool = False) -> dict:
    """
    Run the migration. Returns a summary dict with counts.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    # 1. Find legacy rows grouped by (username, persona)
    cursor.execute("""
        SELECT username, persona, COUNT(*) as cnt
        FROM chat_history
        WHERE chat_id IS NULL OR chat_id LIKE 'legacy_%'
        GROUP BY username, persona
    """)
    legacy_groups = cursor.fetchall()

    summary = {
        "groups_found": len(legacy_groups),
        "total_rows_migrated": 0,
        "sessions_created": 0,
        "dry_run": dry_run,
        "details": [],
    }

    for row in legacy_groups:
        username = row["username"]
        persona = row["persona"]
        cnt = row["cnt"]
        default_chat_id = f"default_{username}_{persona}"

        detail = {
            "username": username,
            "persona": persona,
            "legacy_row_count": cnt,
            "default_chat_id": default_chat_id,
        }

        if dry_run:
            detail["action"] = "would_create_session_and_migrate"
        else:
            # Create the Default Chat session if not exists
            cursor.execute(
                "INSERT OR IGNORE INTO chat_sessions (chat_id, username, persona, title) VALUES (?, ?, ?, ?)",
                (default_chat_id, username, persona, "Default Chat"),
            )
            detail["session_created"] = cursor.rowcount > 0
            if detail["session_created"]:
                summary["sessions_created"] += 1

            # Migrate legacy rows
            cursor.execute(
                "UPDATE chat_history SET chat_id = ? WHERE username = ? AND persona = ? AND (chat_id IS NULL OR chat_id LIKE 'legacy_%')",
                (default_chat_id, username, persona),
            )
            detail["rows_migrated"] = cnt
            summary["total_rows_migrated"] += cnt

        summary["details"].append(detail)

    if not dry_run:
        conn.commit()

    conn.close()
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Migrate legacy chat_id rows to Default Chat"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without applying changes",
    )
    args = parser.parse_args()

    # Ensure DB is initialized
    from kuro_backend.chat_history import init_db
    init_db()

    print("=" * 60)
    print("  Kuro AI — chat_id Legacy Migration")
    print("=" * 60)

    if args.dry_run:
        print("  MODE: DRY RUN (no changes will be made)\n")

    summary = migrate(dry_run=args.dry_run)

    print(f"\n  Groups found: {summary['groups_found']}")
    print(f"  Sessions created: {summary['sessions_created']}")
    print(f"  Total rows migrated: {summary['total_rows_migrated']}")
    print()

    if summary["details"]:
        print("  Details:")
        for d in summary["details"]:
            action = d.get("action", "migrated")
            print(
                f"    - {d['username']}/{d['persona']}: "
                f"{d['legacy_row_count']} rows → {d['default_chat_id']}"
            )

    print("\n  Migration complete.")


if __name__ == "__main__":
    main()
