# Memory Gap Report

Date: 2026-05-22
Scope: Prompt -2 memory-specific enterprise readiness audit.

## Current Memory Map

| Layer | Current path | Storage | Main role |
|---|---|---|---|
| Short-term episodic buffer | `kuro_backend/memory_manager.py` | `kuro_short_term.db`, table `short_term` | Last raw turns per persona, username, chat_id, runtime_id, namespace. |
| Chat history | `kuro_backend/chat_history.py` | `kuro_chat_history.db`, tables `chat_history`, `chat_sessions`, `message_edits`, `uploaded_file_integrity` | Durable conversation transcript, sessions, edits, bookmarks, uploads. |
| Long-term semantic memory | `kuro_backend/perpetual_memory.py` | Mem0 with local Qdrant path from `KURO_MEM0_STORAGE_DIR` | Extracted preferences, habits, personal facts. |
| Chroma/vector document memory | `kuro_backend/ingestion_center/embedding_manager.py` | `kuro_chromadb/ingestion_center` | Ingested document chunks, owner-specific Chroma collections. |
| Structured profile | `kuro_backend/memory_manager.py` | `master_profile.json` | High-authority user/profile facts and shared profile state. |
| Legacy/auxiliary memory JSON | `kuro_backend/perpetual_memory.py` | `kuro_memory.json` | Validated JSON memory blob with backup recovery helpers. |
| Research ledger | `kuro_backend/memory_manager.py` | `kuro_short_term.db`, table `research_ledger` | Append-only research decisions, novelty points, archived file memory. |
| Semantic response cache | `kuro_backend/semantic_cache.py` | Process-local list | Similar-query response reuse with revision tag invalidation. |
| Runtime memory namespace | `kuro_backend/runtime/*`, `memory_coordinator.py` | Runtime YAML plus metadata fields | Bounds memory access by runtime namespace. |
| Ingestion analytics | `kuro_backend/ingestion_center/ingestion_registry.py` | `kuro_ingestion.db` | Dataset/chunk/job/retrieval analytics metadata. |

## Strengths

- `memory_coordinator.py` is already a single orchestration surface for memory read/write fan-out.
- `memory_manager.add_short_term()` writes `runtime_id`, `namespace`, `memory_type`, `status`, and `source`.
- `memory_manager.get_short_term()` filters by `persona_scope`, `username`, `chat_id`, `runtime_id`, and `namespace`.
- `memory_coordinator.safe_mem0_retrieve()` has a hard timeout and fail-closed-to-empty behavior.
- Mem0 writes are deduped by fingerprint and queued per user if a write is already active.
- Mem0 write failures are persisted in `mem0_write_failures` and replayed at startup.
- Ingestion stores document metadata in SQLite and vectors in owner-specific Chroma collections.
- Chat session deletion cascades to `short_term` by `chat_id`.
- Research ledger is append-only and has `source_provenance`.
- Runtime boundary guard is called for Mem0 access when `RuntimeContext` is provided.

## Memory-Specific Issues And Opportunities

| ID | Area | Issue or opportunity | Current evidence path | Risk | Proposed phase |
|---|---|---|---|---|---|
| M-001 | System of record | No single memory system of record; facts can live in SQLite, Mem0/Qdrant, Chroma, JSON, or cache. | `memory_coordinator.py`, `memory_manager.py`, `perpetual_memory.py`, `semantic_cache.py` | Delete/export/provenance cannot be proven globally. | Prompt 2 |
| M-002 | Type model | Memory V2 extends `short_term` instead of owning a clean repository/table set. | `memory_manager.py`, `kuro_backend/memory_v2/*` | Legacy table semantics constrain V3 behavior. | Prompt 2 |
| M-003 | Short-term memory | `short_term` trims to `SHORT_TERM_LIMIT` by deleting older rows. | `memory_manager.add_short_term()` | Raw episodic continuity can be lost unless chat history/research ledger captures it. | Prompt 3 |
| M-004 | Chat history consistency | Chat history and short-term memory are separate writes. | `main.py`, `langgraph_core.py`, `chat_history.py`, `memory_manager.py` | Partial writes can leave transcript and prompt buffer out of sync. | Prompt 4 |
| M-005 | Mem0 provenance | Mem0 memory metadata gets runtime tags, but not a full evidence/provenance envelope. | `memory_coordinator.execute_mem0_extract_task()` | Cannot fully reconstruct source message, model, confidence, retention, or policy context. | Prompt 2 |
| M-006 | Mem0 isolation | Runtime filtering happens after Mem0 retrieval. | `memory_coordinator._filter_mem0_results_by_runtime()` | Unauthorized candidates may be retrieved before filtering, and retrieval quality is affected. | Prompt 3 |
| M-007 | Legacy Mem0 scope | Mem0 rows without runtime metadata are visible to sovereign runtime. | `memory_coordinator._filter_mem0_results_by_runtime()` | Legacy compatibility creates ambiguous scope. | Prompt 2 |
| M-008 | Chroma provenance | Chroma vectors store dataset metadata, but business truth is separate in `kuro_ingestion.db`. | `embedding_manager.py`, `ingestion_registry.py` | Orphan vectors and metadata drift need reconciliation. | Prompt 3 |
| M-009 | Chroma embeddings | Ingestion currently uses `_stable_embedding()` deterministic hash vectors, not semantic model embeddings. | `embedding_manager.py` | Retrieval quality is useful for tests but limited for production semantic recall. | Prompt 3 |
| M-010 | Semantic cache | Cache is process-local and not durable. | `semantic_cache.py` | Multi-worker deployments can serve inconsistent cache behavior. | Prompt 3 |
| M-011 | Semantic cache default | `KURO_SEMANTIC_CACHE_ENABLED` defaults true. | `semantic_cache.py` | Enterprise refactor rule says new features should default off; existing behavior must be documented before changing. | Prompt 0, 3 |
| M-012 | Research ledger retention | `prune_research_ledger()` deletes older rows by fixed days/kind. | `memory_manager.py` | Retention is not policy/tenant-aware and lacks legal hold. | Prompt 2 |
| M-013 | Deletion semantics | Chat session deletion removes chat/session/upload rows and short-term rows, but not Mem0/Chroma/profile facts tied to that chat. | `chat_history.delete_session()`, `perpetual_memory.py`, `ingestion_manager.py` | User delete/export requests cannot be complete. | Prompt 2 |
| M-014 | Master profile | `master_profile.json` is outside SQLite migration/audit and is injected as high-authority profile text. | `memory_manager.py` | Profile facts are not versioned with provenance/conflict lifecycle. | Prompt 2 |
| M-015 | Privacy/PII | Mem0 privacy filter is keyword-based and narrow. | `perpetual_memory.CLIENT_DATA_KEYWORDS` | PII/client data can bypass storage filter. | Prompt 2, 11 |
| M-016 | Memory poisoning | Retrieved Mem0 and ingestion chunks are injected into prompt context with limited source isolation. | `memory_coordinator.build_context_for_llm()` | Untrusted retrieved content can steer generation. | Prompt 3, 11 |
| M-017 | Conflict handling | Conflict/canonicalization exists as optional Canvas 3 logic, not a mandatory memory lifecycle. | `memory_coordinator.execute_memory_write_task()`, `memory_canonicalization.py` | Contradictions may remain as parallel facts. | Prompt 2 |
| M-018 | Concurrency | SQLite writes, Mem0 thread pools, and process-local queues coordinate locally only. | `memory_coordinator.py`, `db_utils.py` | Multi-process deployment may duplicate writes or miss dedupe. | Prompt 1, 2 |
| M-019 | Access logs | Memory read/write events are partially traced but not stored in a central memory access log. | `observability.py`, `CognitionTrace`, `memory_coordinator.py` | Forensics cannot list exactly which memories influenced a response. | Prompt 2, 11 |
| M-020 | Retrieval quality | Retrieval grading exists for response flow, but no Memory V3 acceptance metrics are enforced. | `langgraph_core.py`, `retrieval_quality.py` | Quality regressions are difficult to gate in CI. | Prompt 3 |
| M-021 | Ingestion bridge | Chat bridge retrieves ingestion evidence for every enabled request using owner collection and active datasets. | `memory_coordinator._retrieve_ingestion_evidence()` | Needs explicit authority ranking and citation contract to avoid overusing weak evidence. | Prompt 3 |
| M-022 | Namespace coverage | Not every memory-adjacent table uses runtime namespace fields. | `chat_history.py`, `finance_db.py`, `ingestion_registry.py` | Runtime isolation is uneven across stores. | Prompt 2, 9 |
| M-023 | Backup/restore | Backup system covers DB/JSON/vector directories, but memory restore parity is not tied to Memory V3 tests. | `backup_manager.py`, `SYSTEM_MAP.md` | Recovery can restore files without validating semantic parity. | Prompt -1, 12 |
| M-024 | Source ranking | There is no universal ranking between policy, document chunks, chat, Mem0 preference, and profile. | `memory_coordinator.py`, `memory_manager.py` | Weak memories may outrank authoritative sources. | Prompt 3 |

## Required Deep Assessment Areas

### Short-Term Memory

`kuro_backend/memory_manager.py` stores recent turns in `kuro_short_term.db`. It has useful filters for persona, username, chat_id, runtime_id, namespace, status, and type. The main enterprise gap is that this table is both a hot prompt buffer and a migration target for Memory V2 fields. Memory V3 should separate prompt-window state from durable memory records.

### Chat History

`kuro_backend/chat_history.py` has durable sessions, message edits, bookmarks, uploads, runtime_id on sessions, and username filters. It is stronger than the short-term layer for transcript durability. The gap is consistency: chat and short-term writes are separate, so Memory V3 should define transactional write boundaries or idempotent reconciliation.

### Mem0/Perpetual Memory

`kuro_backend/perpetual_memory.py` stores long-term extracted facts through Mem0 with Qdrant. It has cooldowns, dedupe, and extraction helpers. The gap is governance: Mem0 is not the enterprise source of truth, metadata is incomplete, delete/export is separate, and privacy filtering is keyword-based.

### Chroma/Vector Store

`kuro_backend/ingestion_center/embedding_manager.py` writes owner-specific Chroma collections. `kuro_backend/ingestion_center/ingestion_registry.py` stores dataset/chunk/job metadata. The split is workable, but enterprise retrieval needs a governed record tying vector IDs, chunks, source hashes, lifecycle state, and access logs together.

### Semantic Cache

`kuro_backend/semantic_cache.py` is revision-aware and scoped by persona, username, runtime_id, and runtime_namespace. It is process-local and enabled by default, so it should be inventoried carefully before any enterprise flag changes.

### Ingestion Center

`kuro_backend/ingestion_center/*` is one of the cleaner subsystems: metadata DB, vector manager, analytics, lineage, orphan recovery, archive/delete routes. The largest gap is unification with Memory V3 and stronger source authority/citation contracts.

### Research Ledger

`research_ledger` in `kuro_short_term.db` protects research decisions and novelty points from summary loss. It has `source_provenance`, but lifecycle, legal hold, export/delete, schema validation, and tenant scoping need Memory V3 treatment.

### Runtime Memory Namespace

Runtime namespace appears in short-term rows and Mem0 metadata. The boundary guard exists. However, namespace enforcement is not yet universal across all stores and APIs.

### User And Chat Isolation

Username and chat_id filters exist in short-term and chat history. Chroma uses owner-specific collections. The enterprise gap is tenant/workspace isolation and hard storage-layer filters before retrieval rather than after retrieval.

### Provenance, Conflict, Retention, Deletion

The repo has pieces: source_provenance, memory integrity logs, canonicalization logs, upload integrity hashes, retention pruning, archive/delete routes. Enterprise readiness requires one explicit lifecycle model for every memory record: active, expired, conflicted, deprecated, deleted, legal_hold.

## Memory V3 Acceptance Themes

Memory V3 should be accepted only when:

- New memory writes go through a repository/service layer.
- Every memory record has scope, source, provenance, confidence, salience, status, timestamps, and runtime namespace.
- Retrieval applies hard authorization filters before ranking.
- Chat history, short-term prompt context, Mem0, Chroma, profile JSON, and research ledger have a clear migration/adapter story.
- Delete/export behavior is documented and tested.
- Shadow-read or parity metrics exist before any cutover.

