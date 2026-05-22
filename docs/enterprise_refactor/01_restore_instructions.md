# Enterprise Refactor Phase -1 Restore Instructions

These instructions restore the local runtime files captured in `backups/pre-enterprise-refactor/`. Use them only when intentionally rolling back local runtime state from the safety backup.

## Preconditions

1. Stop the running application, workers, schedulers, and any shell sessions that may write to SQLite, Chroma, Phoenix, upload, or runtime JSON files.
2. Confirm the backup directory exists:

```bash
test -d backups/pre-enterprise-refactor
```

3. Optional but recommended: create a second copy of the current runtime state before overwriting anything.

## Restore SQLite Files

The backup keeps database files under `backups/pre-enterprise-refactor/db/` using their original relative repository paths. Restore all captured SQLite files with:

```bash
cp -a backups/pre-enterprise-refactor/db/. .
```

To restore a single file instead, copy only that backup path to its original location. Example:

```bash
cp -p backups/pre-enterprise-refactor/db/kuro_chat_history.db kuro_chat_history.db
```

## Restore Runtime JSON State

The runtime JSON backup keeps files under `backups/pre-enterprise-refactor/runtime_json/`. Restore all captured JSON state files with:

```bash
cp -a backups/pre-enterprise-refactor/runtime_json/. .
```

Captured runtime JSON files:

```text
kuro_memory.json
master_profile.json
```

## Restore `.env`

The `.env` file was copied to `backups/pre-enterprise-refactor/.env.backup`. Its contents are intentionally not documented.

Restore it with:

```bash
cp -p backups/pre-enterprise-refactor/.env.backup .env
chmod 600 .env
```

## Post-Restore Checks

Run these checks after restore:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

If the unqualified `python` command is needed on this machine, note that it was unavailable during the phase -1 baseline. Use `python3` unless the environment changes.

## Backup Contents

The phase -1 backup contains:

```text
backups/pre-enterprise-refactor/.env.backup
backups/pre-enterprise-refactor/db/finance_data.db
backups/pre-enterprise-refactor/db/kuro_auth.db
backups/pre-enterprise-refactor/db/kuro_backend/kuro_short_term.db
backups/pre-enterprise-refactor/db/kuro_chat_history.db
backups/pre-enterprise-refactor/db/kuro_chromadb/chroma.sqlite3
backups/pre-enterprise-refactor/db/kuro_chromadb/ingestion_center/chroma.sqlite3
backups/pre-enterprise-refactor/db/kuro_compliance.db
backups/pre-enterprise-refactor/db/kuro_compliance_chroma/chroma.sqlite3
backups/pre-enterprise-refactor/db/kuro_finances.db
backups/pre-enterprise-refactor/db/kuro_ingestion.db
backups/pre-enterprise-refactor/db/kuro_intelligence.db
backups/pre-enterprise-refactor/db/kuro_playground.db
backups/pre-enterprise-refactor/db/kuro_short_term.db
backups/pre-enterprise-refactor/db/phoenix_data/phoenix.db
backups/pre-enterprise-refactor/runtime_json/kuro_memory.json
backups/pre-enterprise-refactor/runtime_json/master_profile.json
```
