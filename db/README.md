# Kuro DB Migration Convention

## Purpose
Track SQLite schema evolution with a lightweight `migration_history` table in each database file.

## Baseline
- Version `1` is the initial schema baseline.
- Every `init_db()` routine should ensure the table exists and record v1 once.

## New Migrations
1. Add forward-only SQL in the owning module (`*_db.py`).
2. Guard changes with version checks:
   - `if get_applied_version(conn) < <next_version>:`
3. Apply DDL/DML and then call:
   - `record_migration(conn, <next_version>, '<short description>')`
4. Keep migrations idempotent and safe to rerun.

## Runtime Utilities
Shared helpers live in `kuro_backend/db_utils.py`:
- `get_connection(db_path)`
- `db_retry(...)`
- `ensure_migration_history(conn)`
- `get_applied_version(conn)`
- `record_migration(conn, version, description)`
