# Enterprise Refactor Phase 1 Storage Foundation V2

Phase 1 adds a future-ready storage foundation while keeping every existing SQLite production path active. It does not delete, rewrite, or migrate existing databases, and it does not move Kuro to PostgreSQL yet.

## Scope

Added package:

```text
kuro_backend/storage/
```

Modules:

- `connection.py` - SQLite connection manager with busy timeout, optional WAL, read-only connections, retry/backoff, and transaction context manager.
- `migrations.py` - idempotent helpers for tables, columns, indexes, and migration history.
- `repositories.py` - small repository primitives for future adapters.
- `health.py` - admin storage health checks.
- `data_catalog.py` - catalog of known logical stores.
- `retention.py` - retention policy metadata.
- `idempotency.py` - future idempotency key/result utility.

## Migration Discipline

`ensure_column(conn, table, column_name, column_sql)` uses `PRAGMA table_info` before `ALTER TABLE`, matching the prompt constraint and existing repo migration style.

`ensure_index(conn, index_name, table, columns_sql)` checks `sqlite_master` before creating an index, then uses `CREATE INDEX IF NOT EXISTS`.

`record_migration(db_name, version, description)` records into a store-local `migration_history` table. It accepts either a registered logical store id or a SQLite path. It is idempotent through `INSERT OR IGNORE`.

No existing DB init path was replaced in this phase.

## Data Catalog

Registered logical stores:

| Store | Owner | PII | Backup tier | Notes |
| --- | --- | --- | --- | --- |
| `auth` | `kuro_backend.auth_db` | medium | tier1 | Dashboard identity and login security. |
| `chat_history` | `kuro_backend.chat_history` | high | tier1 | Conversations, sessions, and upload integrity. |
| `short_term` | `kuro_backend.memory_manager` | high | tier1 | Legacy short-term and memory coordination data. |
| `intelligence` | `kuro_backend.intelligence_db` | medium | tier1 | Briefings, audit events, backups, notification DLQ. |
| `finance` | `kuro_backend.finance_db` | medium | tier1 | Finance, cost, market, and fiscal sentinel data. |
| `compliance` | `kuro_backend.compliance_db` | medium | tier2 | Compliance evidence and audit analysis. |
| `ingestion` | `kuro_backend.ingestion_center.ingestion_registry` | medium | tier2 | Dataset registry and ingestion metadata. |
| `memory_v3` | `kuro_backend.memory_v3` | high | future | Future store only; not required in Phase 1. |

## Admin APIs

All routes require the existing admin authentication helper:

```text
GET /api/admin/storage/health
GET /api/admin/storage/catalog
GET /api/admin/storage/migrations
```

Health checks report:

- DB file existence
- read-only open status
- migration history table presence
- current SQLite journal mode and WAL status
- last backup status if available

Missing future stores, such as `memory_v3`, are reported as `optional_missing` and do not fail the whole snapshot.

## Idempotency Utility

`idempotency.py` can hash:

- route
- user
- request body
- optional `chat_id`

It can also persist and retrieve a result in an `idempotency_results` table. This is intentionally not wired into production endpoints yet.

## Verification

Phase 1 adds `tests/test_storage_v2.py` for:

- migration helper idempotency
- `ensure_column` run twice
- `ensure_index` run twice
- catalog secret-safety
- admin route authorization
- missing optional DB health behavior

Acceptance gate:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

The unqualified `python` command is unavailable in this environment, as recorded in the phase -1 baseline.
