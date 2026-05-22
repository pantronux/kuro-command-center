# Enterprise Refactor Phase 2 Memory V3 Core

Phase 2 introduces Memory V3 as an additive, provenance-first memory subsystem. It does not replace the existing `memory_coordinator`, `memory_manager`, Mem0, Chroma, short-term SQLite, research ledger, or chat history paths. `KURO_MEMORY_V3_ENABLED` remains default `false`.

## Core Package

Added package:

```text
kuro_backend/memory_v3/
```

Modules:

- `schemas.py` - Pydantic models for events, items, assertions, read/write requests/results, conflicts, and policies.
- `store.py` - SQLite source-of-truth store and idempotent schema creation.
- `events.py` - deterministic write-event and idempotency-key builders.
- `writer.py` - write pipeline: scope validation, event append, normalization, type classification, canonical key assignment, duplicate/conflict detection, sensitivity assignment, upsert, access logging.
- `reader.py` - basic scoped read path for core tests and diagnostics.
- `policy.py` - scope, memory type, retention, sensitivity, and read/write/redact checks.
- `provenance.py` - source/provenance envelope helpers.
- `conflict.py` - deterministic duplicate and contradiction detection without LLM calls.
- `retention.py` - expiry, low-confidence temporary review marking, and redaction orchestration.
- `privacy.py` - sensitivity classification and text redaction helpers.
- `telemetry.py` - lightweight logging/timing helpers.
- `adapters.py` - bridge adapters for legacy short-term, chat history, research ledger, Mem0 records, and ingestion metadata.
- `health.py` - admin and public-safe health/status snapshots.

## SQLite Tables

Memory V3 creates these tables in `kuro_memory_v3.db` by default:

```text
memory_events
memory_items
memory_assertions
memory_links
memory_conflicts
memory_access_log
memory_retention_policies
memory_redaction_log
memory_embedding_refs
memory_source_refs
```

Schema initialization is idempotent and uses `CREATE TABLE IF NOT EXISTS` plus stable indexes. This phase does not migrate legacy memory rows.

## Design Rules

- Memory writes are events first.
- Canonical memory items are derived from events.
- Every memory item carries scope and provenance.
- Every read/write/update/redaction is access-logged.
- Conflicts are represented explicitly instead of silently overwriting truth.
- Retention marks records expired or redacted; it does not physically delete by default.
- Core conflict handling is deterministic and makes no LLM calls.
- Adapters can read/bridge existing stores when Memory V3 is enabled later, but production paths are not switched in this phase.

## API

Admin-only:

```text
GET /api/admin/memory-v3/health
GET /api/admin/memory-v3/conflicts
GET /api/admin/memory-v3/access-log
POST /api/admin/memory-v3/expire
```

User-safe:

```text
GET /api/memory-v3/status
```

The user-safe status route returns only high-level state:

```json
{
  "enabled": false,
  "initialized": false,
  "status": "not_initialized"
}
```

It does not expose other users, raw DB paths, prompt stacks, memory namespaces, tools, secrets, or internal topology.

## Isolation

The store filters records by:

- `workspace_id`
- `username`
- `runtime_id`
- `persona_scope`
- `chat_id`

The tests cover user, runtime, and chat isolation.

## Verification

Phase 2 adds `tests/test_memory_v3_core.py` for:

- idempotent schema init
- event append
- write idempotency
- item upsert
- user/runtime/chat isolation
- basic conflict detection
- retention expiry
- redaction
- admin route authorization
- public status safety
- default disabled behavior not affecting existing chat capability

Acceptance gate:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

The unqualified `python` command is unavailable in this environment, as recorded in the phase -1 baseline.
