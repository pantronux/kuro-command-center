# Data Store Inventory

Date: 2026-05-22
Scope: current storage/data-plane inventory for Prompt -2.

## SQLite Stores

| Logical store | Path / resolver | Owning modules | Notable tables | Enterprise notes |
|---|---|---|---|---|
| Auth | `kuro_auth.db` under working dir | `kuro_backend/auth_db.py`, `main.py` | Users, login stats, proactive greeting state per `SYSTEM_MAP.md` | Contains authentication data and should be high PII. |
| Chat history | `settings.WORKING_DIR/kuro_chat_history.db` | `kuro_backend/chat_history.py`, `main.py` | `chat_history`, `uploaded_file_integrity`, `chat_sessions`, `message_edits`, `migration_history` | Durable transcript and upload chain-of-custody metadata. |
| Short-term memory | `settings.WORKING_DIR/kuro_short_term.db` | `kuro_backend/memory_manager.py`, `memory_coordinator.py`, `langgraph_core.py`, `dreaming_worker.py` | `short_term`, `short_term_summaries`, `research_ledger`, `dreaming_locks`, `dreaming_cycles`, `dream_notifications`, `session_file_store`, `mem0_write_failures`, Canvas 1/2/3 telemetry tables | Hot memory, research ledger, runtime state, and governance logs are co-located. |
| Intelligence | repo root `kuro_intelligence.db` | `kuro_backend/intelligence_db.py`, `observability`, `main.py` | `intelligence_briefings`, `research_sources`, `backup_log`, boundary/runtime/eval logs per `SYSTEM_MAP.md` | Critical audit and observability store. |
| Finance/Market | `KURO_FINANCE_DB_PATH` or repo root `kuro_finances.db` | `kuro_backend/finance_db.py`, `price_ticker_worker.py`, `market_sentinel.py`, `main.py` | `monthly_budget`, `recurring_expenses`, `api_usage_daily`, `watched_symbols`, `market_hud_snapshot`, `market_sentinel_history`, `market_sentinel_stocks`, `market_price_history`, `user_pinned_stocks` | Decision-support financial and market state; never auto-trading. |
| Compliance legacy | `kuro_compliance.db` | `kuro_backend/compliance_db.py`, disabled routes | Legacy compliance tables per `SYSTEM_MAP.md` | Routes mostly return 410, but data may still exist and require retention/export policy. |
| Ingestion | repo root `kuro_ingestion.db` | `kuro_backend/ingestion_center/ingestion_registry.py` | `ingested_datasets`, `dataset_chunks`, `ingestion_jobs`, `retrieval_analytics`, `dataset_lineage`, `migration_history` | Strong candidate for storage catalog and Memory V3 document_chunk migration. |
| Phoenix | `phoenix_data/phoenix.db` through env/defaults | `kuro_backend/observability.py` | Phoenix-managed trace DB | Operational trace store; sensitive prompts/responses may be present. |
| Playground | `playground_runtime/db/playground_db.py` | `playground_runtime/*` | Playground sessions/executions/integrity artifacts | Separate runtime for forensic playground; should be catalogued. |

## Vector And Memory Stores

| Store | Path / resolver | Owning modules | Notes |
|---|---|---|---|
| Mem0/Qdrant local store | `KURO_MEM0_STORAGE_DIR` default `/home/kuro/kuro_mem0` | `kuro_backend/perpetual_memory.py`, `memory_coordinator.py` | Long-term extracted preferences/habits/facts. Not governed as a single source of truth. |
| General Chroma root | `settings.WORKING_DIR/kuro_chromadb` | `memory_manager.py`, `tools/base_tools.py`, maintenance scripts | Document/vector data referenced by system map. |
| Ingestion Chroma root | `settings.WORKING_DIR/kuro_chromadb/ingestion_center` | `kuro_backend/ingestion_center/embedding_manager.py` | Owner-specific collections named `kuro_ingestion_{owner_username}`. |
| Semantic cache | Process memory | `kuro_backend/semantic_cache.py`, `langgraph_core.py`, `memory_coordinator.py` | Scoped by persona, username, runtime_id, namespace; invalidates by tag; not durable. |

## JSON Runtime State

| File | Owning modules | Notes |
|---|---|---|
| `master_profile.json` | `kuro_backend/memory_manager.py` | High-authority profile state injected into prompts. Atomic writes. Needs provenance/version lifecycle. |
| `kuro_memory.json` | `kuro_backend/perpetual_memory.py` | Validated schema with backup recovery and atomic writes. Auxiliary/legacy memory state. |
| Runtime YAML configs | `config/runtime/*.runtime.yaml` | `kuro_backend/runtime/runtime_registry.py` | Declarative runtime configs, prompt stack IDs, structured output contracts. |
| Rollout JSONL | repo root `rollout-*.jsonl` | operational artifact | Should remain runtime/audit artifact, not code. |

## File And Object-Like Stores

| Store | Path | Owning modules | Notes |
|---|---|---|---|
| Uploaded files | `uploaded_files/{username}/{category}/` | `main.py`, `kuro_backend/tools/base_tools.py`, `file_retention_worker.py`, `ingestion_center/ingestion_security.py` | Per-user partitioning exists; upload integrity metadata in chat DB. |
| Ingestion source files | `uploaded_files/{username}/ingestion_center/` | `ingestion_center/ingestion_manager.py` | Source of document ingestion records. |
| Archive sidecars | `.archive/{username}/` | `file_retention_worker.py` per `SYSTEM_MAP.md` | Archived file summaries and metadata. |
| Exports | `exports/` | `kuro_backend/export_engine/*` | Generated reports and async PDF jobs. |
| Backups | `backups/` | `kuro_backend/backup_manager.py`, `main.py` | Nightly/manual/pre-migration backups. |
| Logs | `logs/`, `kuro_sovereign.log` | `logger_setup.py`, `main.py` | Operational logs; may include sensitive content. |

## Storage Strengths

- Shared SQLite helper sets WAL and busy timeout.
- Several DB modules call pre-migration snapshots before schema bootstrap.
- `conftest.py` is documented in `SYSTEM_MAP.md` as redirecting test DB paths to temporary locations.
- Runtime stores are gitignored in `.gitignore`.
- Ingestion has lineage, retrieval analytics, orphan recovery, archive/delete flows.
- Chat uploads record SHA-256 and expiration metadata.

## Storage Gaps

1. No central storage package yet.
2. No data catalog with owner, PII level, retention policy, backup tier, and tables.
3. No unified migration runner or migration report across SQLite files.
4. Several modules bootstrap schema at import time.
5. Store paths use mixed conventions: working dir, repo root, env overrides, and absolute defaults.
6. Vector stores and SQLite metadata can drift.
7. Mem0/Qdrant is not represented in migration history.
8. Runtime JSON files are not governed with the same audit model as DB rows.
9. Backups exist, but restore validation needs a documented baseline.
10. No idempotency persistence layer for mutating API operations.

## Recommended Next Inventory Work

Prompt 1 should create `kuro_backend/storage/` and register at least these logical stores: `auth`, `chat_history`, `short_term`, `intelligence`, `finance`, `compliance`, `ingestion`, `memory_v3_future`, `phoenix`, `mem0`, and `chroma_ingestion`.

