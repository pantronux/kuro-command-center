# KURO AI — Enterprise-Ready Major Refactor Codex Prompt Pack

**Target:** Kuro AI enterprise-ready refactor across backend, memory, storage, chat, Market Sentinel, Telegram, API, middleware, UI/UX, provider registry, observability, deployment, and governance.  
**Execution mode:** Controlled, one prompt at a time.  
**Repository assumption:** Python/FastAPI monolith with LangGraph core, SQLite stores, Chroma/Mem0, Telegram, OpenClaw bridge, Market Sentinel, Vanilla JS + Jinja frontend.  
**Generated for:** Codex execution.  
**Date:** 2026-05-22.

---

## 0. How to Use This File

Paste **one prompt at a time** into Codex.

Do not run the whole pack in one pass.

Recommended execution:

```text
Prompt -2  -> repo audit and enterprise gap report
Prompt -1  -> safety prep and branch/backup
Prompt 0   -> enterprise config and feature flag baseline
Prompt 1   -> storage foundation
Prompt 2   -> Memory V3 core architecture
Prompt 3   -> Memory V3 retrieval, grounding, and context packing
Prompt 4   -> chat, streaming, history, and session UX backend
Prompt 5   -> provider/model registry
Prompt 6   -> tool runtime, web search, deep research, agent mode, task/reminder
Prompt 7   -> Market Sentinel V2
Prompt 8   -> Telegram API V2
Prompt 9   -> overall API/middleware hardening
Prompt 10  -> frontend ChatGPT-like UX refactor
Prompt 11  -> enterprise observability/evaluation/security
Prompt 12  -> deployment, secrets, backup, runbooks
Prompt 13  -> performance and bug-fix sweep
Prompt 14  -> docs, SYSTEM_MAP, and final acceptance report
```

After each prompt:

```bash
python -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
git diff --stat
```

If the repository has `ruff`:

```bash
ruff check .
```

If a prompt modifies frontend JS/CSS/HTML, also run the available frontend/static contract tests. If no frontend test runner exists, create smoke tests for template rendering and critical JS contract behavior where feasible.

Commit after every successful phase:

```bash
git add .
git commit -m "Enterprise Refactor Phase X: <phase-name>"
```

---

## 1. Global Execution Rules for Codex

Apply these rules to every prompt in this file.

```text
GLOBAL EXECUTION RULES

1. Do not break existing V2.1.0 runtime behavior.
2. Maintain backward compatibility for:
   - /api/chat
   - /api/chat/stream
   - existing chat history
   - current Telegram notifications
   - current Market Sentinel behavior
   - current OpenClaw bridge behavior
   - current admin routes
3. Every new feature must be behind a feature flag and disabled by default unless explicitly stated.
4. Never leave pass, TODO, FIXME, placeholder returns, NotImplementedError, or fake implementation in any executed production path.
5. If a feature cannot be fully implemented, keep it disabled and return a safe structured error.
6. Do not delete existing data.
7. All migrations must be idempotent.
8. For SQLite migrations, do not use ALTER TABLE ADD COLUMN IF NOT EXISTS directly. Use PRAGMA table_info() first.
9. Never make real external API calls in tests. Use mocks/fakes.
10. Do not hardcode API keys, tokens, provider credentials, user identities, or secrets.
11. Do not expose internal runtime topology in public routes.
12. Full runtime/provider/memory/tool configuration must be admin-only.
13. Use existing admin authorization conventions where available.
14. Preserve SSE contract:
    - deterministic termination
    - explicit error event
    - done event
    - trace_id propagation
15. Preserve traceability:
    - request_id / trace_id
    - username
    - workspace_id if available
    - runtime_id
    - chat_id
    - provider/model
    - tool usage
    - memory reads/writes
16. Treat financial/market outputs as decision support, not investment advice.
17. Market Sentinel must never claim guaranteed stock accuracy.
18. Never implement automatic trade execution.
19. Do not resurrect removed legacy reminders/habits code directly. If task/reminder is required, implement a new clean subsystem.
20. Update SYSTEM_MAP.md only after code and tests pass.
```

---

## 2. Research and Standards Anchors

Use these as design anchors. Do not blindly implement every idea; translate them into practical Kuro-compatible architecture.

```text
Enterprise AI governance:
- NIST AI Risk Management Framework
- NIST AI RMF Generative AI Profile
- OWASP Top 10 for LLM / GenAI Applications

AI observability:
- OpenTelemetry GenAI semantic conventions
- OpenInference conventions
- Phoenix tracing / existing Kuro observability

Provenance and evidence modeling:
- W3C PROV-O
- W3C SHACL
- CASE/UCO and digital forensic chain-of-custody ideas
- Raw evidence before normalization
- Canonical trace with mapping manifest

Memory and retrieval:
- Retrieval-Augmented Generation
- Self-RAG
- Corrective RAG
- MemGPT
- Reflexion
- Generative Agents memory architecture

Kuro-specific system direction:
- Runtime isolation
- Memory namespace isolation
- Structured output validation
- Boundary guard
- Cognitive trace
- Provider abstraction
- Admin-only topology
```

---

## 3. Target End-State

The enterprise refactor should move Kuro from:

```text
Monolithic personal sovereign AI
```

toward:

```text
Enterprise-grade AI runtime platform with:
- reliable memory
- clean storage
- robust chat
- governed tools
- auditable API
- provider/model abstraction
- source-grounded research
- market intelligence support
- Telegram bridge
- ChatGPT-like UX
- admin control plane
- observability and evaluation
- deployment hardening
```

But do this incrementally.

---

# PROMPT -2 — Repository Audit and Enterprise Gap Report

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Perform a zero-functional-change enterprise readiness audit of the current repository before any major refactor.

Hard constraints:
- Do not modify functional code.
- Do not migrate databases.
- Do not change runtime behavior.
- Do not add dependencies unless absolutely necessary for static analysis.
- Produce documentation only.

Tasks:
1. Read SYSTEM_MAP.md, main.py, kuro_backend/config.py, kuro_backend/langgraph_core.py, kuro_backend/memory_coordinator.py, kuro_backend/memory_manager.py, kuro_backend/perpetual_memory.py, kuro_backend/chat_history.py, kuro_backend/db_utils.py, kuro_backend/telegram_notifier.py, kuro_backend/finance_db.py, kuro_backend/price_ticker_worker.py, kuro_backend/dreaming_worker.py, kuro_backend/execution/openclaw_bridge.py, web_interface/templates/index.html, and web_interface/static/js/app.js.
2. Create docs/enterprise_refactor/00_repo_audit.md.
3. Create docs/enterprise_refactor/00_enterprise_gap_matrix.md.
4. Create docs/enterprise_refactor/00_memory_gap_report.md.
5. Create docs/enterprise_refactor/00_api_surface_inventory.md.
6. Create docs/enterprise_refactor/00_data_store_inventory.md.
7. Create docs/enterprise_refactor/00_frontend_inventory.md.

Audit dimensions:
- Backend architecture
- Memory architecture
- Storage/database design
- Chat and streaming reliability
- Market Sentinel
- Telegram API
- Overall API/middleware
- Frontend UI/UX
- Observability
- Security/RBAC
- Deployment/secrets
- Tests
- Documentation

For each dimension include:
- Current modules
- Current strengths
- Current risks
- Enterprise gaps
- Proposed next refactor phase
- Blocker or non-blocker label

Memory report must deeply assess:
- short-term memory
- chat history
- Mem0/perpetual memory
- Chroma/vector store
- semantic cache
- ingestion center
- research ledger
- runtime memory namespace
- user isolation
- chat_id isolation
- provenance
- conflict handling
- retention
- deletion
- consistency under concurrent writes
- retrieval quality
- memory poisoning risk
- privacy/PII risk

Acceptance criteria:
- No functional code changed.
- Documentation files exist.
- Audit references exact repo paths.
- Audit identifies at least 20 enterprise gaps.
- Memory gap report identifies at least 15 memory-specific issues or improvement opportunities.
- Run:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase -2: repository enterprise audit
```

---

# PROMPT -1 — Safety Prep, Branch, Backup, and Baseline

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Prepare a safe execution baseline for a major enterprise refactor.

Hard constraints:
- Do not change functional code.
- Do not run destructive migrations.
- Do not delete data.
- Preserve current runtime.

Tasks:
1. Create docs/enterprise_refactor/01_safety_baseline.md.
2. Record:
   - current git commit hash
   - current branch
   - Python version
   - installed package list if available
   - all SQLite files found
   - all runtime JSON state files found
   - all .env-like files found without printing secrets
   - all Chroma/vector directories found
   - all upload/runtime directories found
3. Create backups/pre-enterprise-refactor/ if missing.
4. Copy all *.db, *.sqlite, *.sqlite3 files into backups/pre-enterprise-refactor/.
5. Copy runtime JSON files such as kuro_memory.json and master_profile.json if present.
6. Copy .env to backups/pre-enterprise-refactor/.env.backup if present, but do not print its content.
7. Add or update .gitignore if backups or runtime files are not ignored.
8. Add docs/enterprise_refactor/01_restore_instructions.md explaining how to restore DB/runtime files from the backup.
9. Add tests/test_enterprise_refactor_baseline.py to verify:
   - backup directory exists after safety prep
   - restore docs exist
   - runtime files are not accidentally committed if already ignored

Acceptance criteria:
- No functional code changed.
- Backup docs exist.
- Restore docs exist.
- Compile and tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase -1: safety baseline and backups
```

---

# PROMPT 0 — Enterprise Config, Feature Flags, and Refactor Control Plane

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Create an enterprise refactor control plane using typed settings and feature flags, without changing default behavior.

Hard constraints:
- Default behavior must remain unchanged.
- All new enterprise features must default OFF.
- Do not replace existing chat, memory, market, or Telegram paths yet.
- Do not expose secrets.
- Do not expose full internal topology publicly.

Tasks:
1. Extend kuro_backend/config.py with typed settings for enterprise refactor flags:
   - KURO_ENTERPRISE_REFACTOR_ENABLED=false
   - KURO_MEMORY_V3_ENABLED=false
   - KURO_STORAGE_V2_ENABLED=false
   - KURO_CHAT_V2_ENABLED=false
   - KURO_MARKET_SENTINEL_V2_ENABLED=false
   - KURO_TELEGRAM_V2_ENABLED=false
   - KURO_PROVIDER_REGISTRY_V2_ENABLED=false
   - KURO_AGENT_TOOLS_V2_ENABLED=false
   - KURO_TASKS_V2_ENABLED=false
   - KURO_DEEP_RESEARCH_V2_ENABLED=false
   - KURO_WEB_SEARCH_V2_ENABLED=false
   - KURO_FRONTEND_V2_ENABLED=false
   - KURO_ADMIN_SETTINGS_V2_ENABLED=false
   - KURO_ENTERPRISE_OBSERVABILITY_ENABLED=false
   - KURO_API_V2_ENABLED=false
2. Add provider-related env fields but do not use them yet:
   - GEMINI_API_KEY
   - OPENAI_API_KEY
   - ANTHROPIC_API_KEY
   - DEEPSEEK_API_KEY
   - KURO_DEFAULT_PROVIDER=gemini
   - KURO_DEFAULT_MODEL_ALIAS=gemini_fast
   - KURO_MODEL_GEMINI_FAST=gemini-3-flash-preview
   - KURO_MODEL_OPENAI_NANO=gpt-5.4-nano
   - KURO_MODEL_CLAUDE_FAST=claude-haiku-4-5
   - KURO_MODEL_DEEPSEEK_FAST=deepseek-v4-flash
3. Important:
   - Treat model names as configurable aliases.
   - Do not fail app startup if a provider key is missing.
   - Missing keys should only disable that provider at runtime.
4. Create kuro_backend/enterprise_flags.py with:
   - is_enabled(flag_name)
   - get_enterprise_flag_snapshot(admin=False)
   - require_feature_enabled(flag_name) returning safe structured error if disabled
5. Add admin-only route:
   - GET /api/admin/enterprise-flags
6. Add public-safe route:
   - GET /api/capabilities
   This route must only show high-level feature availability, not secrets or internal config.
7. Add tests:
   - test_enterprise_flags_default_off
   - test_capabilities_public_safe
   - test_admin_enterprise_flags_requires_admin
   - test_missing_provider_keys_do_not_break_startup
8. Add .env.example entries for all new env keys with placeholder values only.
9. Update docs/enterprise_refactor/02_feature_flags.md.

Acceptance criteria:
- Existing tests pass.
- Default behavior unchanged.
- Public /api/capabilities does not leak model keys, prompt stack, memory namespaces, tools, DB paths, or secrets.
- Admin route requires existing admin auth.
- Run:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 0: enterprise feature flag baseline
```

---

# PROMPT 1 — Storage Foundation V2

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Harden storage and create a future-ready database abstraction without forcing a full migration away from SQLite yet.

Context:
Kuro currently uses multiple SQLite databases and a shared db_utils.py. Enterprise readiness requires stronger migration discipline, repository patterns, data inventory, retention metadata, backup awareness, and a future path to PostgreSQL/pgvector.

Hard constraints:
- Do not delete or rewrite existing DBs.
- Do not migrate to PostgreSQL now.
- Do not change existing table behavior unless safely additive.
- All migrations must be idempotent.
- Use PRAGMA table_info before ALTER TABLE.
- Default runtime must remain SQLite-compatible.

Tasks:
1. Create kuro_backend/storage/ package:
   - __init__.py
   - connection.py
   - migrations.py
   - repositories.py
   - health.py
   - data_catalog.py
   - retention.py
   - idempotency.py
2. Implement StorageConnectionManager:
   - SQLite connection helper using existing db_utils patterns
   - busy timeout
   - WAL mode where safe
   - retry/backoff
   - transaction context manager
   - read-only connection option
3. Implement a migration helper:
   - ensure_column(conn, table, column_name, column_sql)
   - ensure_index(conn, index_name, table, columns_sql)
   - ensure_table(conn, ddl)
   - record_migration(db_name, version, description)
   - get_migration_history(db_name)
4. Implement a Data Catalog registry:
   - logical_store_id
   - db_path
   - owner_module
   - tables
   - pii_level: none/low/medium/high
   - retention_policy
   - backup_tier
   - enterprise_notes
5. Register known stores:
   - auth
   - chat_history
   - short_term
   - intelligence
   - finance
   - compliance
   - ingestion
   - memory_v3 future store
6. Add admin-only API:
   - GET /api/admin/storage/health
   - GET /api/admin/storage/catalog
   - GET /api/admin/storage/migrations
7. Add health checks:
   - DB file exists
   - can open read-only
   - migration_history exists where expected
   - WAL mode if enabled
   - last backup status if available
8. Add idempotency key utility for future write endpoints:
   - hash request body + route + user + optional chat_id
   - persist idempotency key result where feasible
   - do not wire into production endpoints yet unless safe
9. Add tests:
   - migration helper idempotency
   - ensure_column run twice
   - ensure_index run twice
   - storage catalog does not expose secrets
   - admin storage routes require admin
   - health check handles missing optional DB gracefully
10. Add docs/enterprise_refactor/03_storage_v2.md.

Acceptance criteria:
- Existing DB behavior unchanged.
- No production DB deleted.
- New storage package compiles.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 1: storage foundation v2
```

---

# PROMPT 2 — Memory V3 Core Architecture

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Build Memory V3 core as an enterprise-grade memory subsystem while keeping existing memory behavior active by default.

This is the most critical phase.

Current memory-related modules include:
- memory_coordinator.py
- memory_manager.py
- perpetual_memory.py
- semantic_cache.py
- embedding_cache.py
- ingestion_center
- chat_history.py
- research_ledger
- Mem0/Chroma integration

Target:
Introduce Memory V3 as a controlled, auditable, isolated, provenance-first memory subsystem.

Hard constraints:
- KURO_MEMORY_V3_ENABLED must default false.
- Existing memory path must remain active unless flag is explicitly enabled.
- Do not delete Mem0, Chroma, short_term, research_ledger, or chat history logic.
- Do not migrate all memory data yet.
- Do not write fake placeholders.
- All schema migrations must be idempotent.
- No external LLM calls in tests.

Memory V3 design principles:
1. Memory is not a blob.
2. Memory writes are events.
3. Canonical memory items are derived from events.
4. Every memory item must have provenance.
5. Every memory read/write must be scoped.
6. Retrieval must be explainable.
7. Conflict is expected, not exceptional.
8. Retention is policy-driven.
9. Sensitive memory must be explicitly classified.
10. Vector recall is only one retrieval channel, not the source of truth.

Memory types:
- ephemeral_context
- working_memory
- episodic_memory
- semantic_memory
- procedural_memory
- operational_memory
- evidence_memory
- reflective_memory
- task_memory
- market_signal_memory
- user_preference_memory
- system_policy_memory

Required scopes:
- workspace_id
- username
- runtime_id
- persona_scope
- chat_id
- source_type
- source_id

Tasks:
1. Create kuro_backend/memory_v3/ package:
   - __init__.py
   - schemas.py
   - store.py
   - events.py
   - writer.py
   - reader.py
   - policy.py
   - provenance.py
   - conflict.py
   - retention.py
   - privacy.py
   - telemetry.py
   - adapters.py
   - health.py
2. Create Memory V3 schema using SQLite for now:
   - memory_events
   - memory_items
   - memory_assertions
   - memory_links
   - memory_conflicts
   - memory_access_log
   - memory_retention_policies
   - memory_redaction_log
   - memory_embedding_refs
   - memory_source_refs
3. Table design must include:
   memory_events:
   - event_id
   - event_type
   - idempotency_key
   - workspace_id
   - username
   - runtime_id
   - persona_scope
   - chat_id
   - source_type
   - source_id
   - payload_json
   - created_at
   - trace_id

   memory_items:
   - memory_id
   - canonical_key
   - memory_type
   - status: active/deprecated/conflicted/expired/redacted
   - content
   - normalized_summary
   - confidence_score
   - importance_score
   - sensitivity_level
   - workspace_id
   - username
   - runtime_id
   - persona_scope
   - chat_id_nullable
   - created_at
   - updated_at
   - expires_at
   - source_event_id
   - provenance_json

   memory_assertions:
   - assertion_id
   - memory_id
   - subject
   - predicate
   - object
   - qualifiers_json
   - confidence_score
   - evidence_refs_json

   memory_links:
   - link_id
   - source_memory_id
   - target_memory_id
   - link_type
   - confidence_score

   memory_conflicts:
   - conflict_id
   - memory_id_a
   - memory_id_b
   - conflict_type
   - status
   - resolution_strategy
   - resolution_notes
   - created_at
   - resolved_at

   memory_access_log:
   - access_id
   - access_type: read/write/update/delete/redact
   - memory_id_nullable
   - query_hash_nullable
   - workspace_id
   - username
   - runtime_id
   - chat_id_nullable
   - trace_id
   - created_at
4. Implement Pydantic models:
   - MemoryEvent
   - MemoryItem
   - MemoryAssertion
   - MemoryWriteRequest
   - MemoryWriteResult
   - MemoryReadRequest
   - MemoryReadResult
   - MemoryConflict
   - MemoryPolicy
5. Implement MemoryV3Store:
   - init_db()
   - append_event()
   - upsert_memory_item()
   - get_memory_item()
   - search_memory_items_basic()
   - log_access()
   - mark_expired()
   - redact_memory()
   - list_conflicts()
   - create_conflict()
   - resolve_conflict()
6. Implement MemoryV3Policy:
   - validate_scope()
   - allowed_memory_types_for_runtime()
   - retention_days_for_type()
   - sensitivity_rules()
   - can_read()
   - can_write()
   - can_redact()
7. Implement MemoryWriter pipeline:
   - validate scope
   - compute idempotency key
   - append event
   - normalize candidate memory
   - classify memory type
   - assign canonical_key
   - detect duplicate
   - detect conflict
   - assign confidence/importance/sensitivity
   - upsert canonical memory item
   - log access
   - return structured result
8. Implement MemoryConflictResolver:
   - duplicate detection by canonical_key
   - simple contradiction heuristics
   - recency-aware conflict marking
   - confidence-aware conflict marking
   - no LLM calls in core resolver
   - optional LLM adjudication must be disabled by default
9. Implement MemoryRetentionEngine:
   - expire stale memories
   - mark low-confidence temporary memory for review
   - redact sensitive items when requested
   - do not physically delete by default
10. Implement adapters but do not fully switch production path:
   - LegacyShortTermAdapter
   - ChatHistoryAdapter
   - ResearchLedgerAdapter
   - Mem0Adapter
   - IngestionAdapter
   These adapters should help read from existing stores or write bridging events when flag is enabled.
11. Add admin-only routes:
   - GET /api/admin/memory-v3/health
   - GET /api/admin/memory-v3/conflicts
   - GET /api/admin/memory-v3/access-log
   - POST /api/admin/memory-v3/expire
12. Add user-safe route:
   - GET /api/memory-v3/status
   It must not reveal other users, internal topology, raw DB paths, or secrets.
13. Add tests:
   - memory_v3_init_idempotent
   - memory_write_event_appends
   - memory_write_idempotency
   - memory_item_upsert
   - user_isolation
   - runtime_isolation
   - chat_id_isolation
   - conflict_detection_basic
   - retention_expiry
   - redact_memory
   - admin_routes_require_admin
   - public_status_safe
   - Memory V3 disabled by default does not affect existing chat
14. Add docs/enterprise_refactor/04_memory_v3_core.md.

Acceptance criteria:
- Existing memory behavior remains default.
- Memory V3 can be initialized safely.
- Memory V3 tests pass.
- No external API calls in tests.
- Compile and tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 2: memory v3 core architecture
```

---

# PROMPT 3 — Memory V3 Retrieval, Grounding, and Context Packing

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Implement Memory V3 retrieval and context packing with hybrid retrieval, provenance, isolation, and explainability.

Hard constraints:
- KURO_MEMORY_V3_ENABLED defaults false.
- Do not replace existing build_context_for_llm unless flag is explicitly enabled.
- Existing memory_coordinator path must continue working.
- No external LLM calls in tests.
- No cross-user or cross-runtime memory leakage.

Target:
When Memory V3 is enabled, Kuro should retrieve memory using:
- scope filtering
- keyword search
- semantic/vector adapter when available
- recency
- confidence
- importance
- provenance quality
- source reliability
- conflict status
- retention status
- token budget packing

Tasks:
1. Extend kuro_backend/memory_v3/reader.py:
   - MemoryV3Reader
   - retrieve()
   - retrieve_by_keyword()
   - retrieve_by_semantic_adapter()
   - retrieve_recent()
   - retrieve_high_importance()
   - retrieve_task_related()
   - retrieve_market_signal_related()
2. Extend kuro_backend/memory_v3/schemas.py:
   - MemoryRetrievalCandidate
   - MemoryContextPack
   - MemoryCitation
   - MemoryRetrievalDiagnostics
3. Implement ranking:
   score = weighted combination of:
   - lexical relevance
   - semantic relevance if available
   - recency
   - confidence_score
   - importance_score
   - source reliability
   - runtime/persona/chat match strength
   - conflict penalty
   - expired/deprecated penalty
4. Implement source reliability:
   - direct_user_statement
   - uploaded_file
   - tool_result
   - web_search
   - market_data_provider
   - provider_response
   - system_config
   - inference
   - unknown
5. Implement context packer:
   - group by memory type
   - remove duplicates
   - collapse near-duplicates
   - include citations/provenance IDs
   - include conflict warnings
   - include freshness notes
   - enforce token budget
   - never include internal raw DB paths or secrets
6. Implement memory anti-poisoning checks:
   - prompt injection markers in remembered content
   - hidden system prompt requests
   - tool override attempts
   - instruction-like memories that try to alter system behavior
   - mark as suspicious and do not inject as instruction
7. Add integration in memory_coordinator.py:
   - if KURO_MEMORY_V3_ENABLED=true, call MemoryV3Reader for context pack
   - otherwise use existing flow unchanged
   - keep fallback to existing context if Memory V3 fails
8. Add telemetry:
   - retrieval candidate count
   - selected memory count
   - dropped expired count
   - conflict count
   - suspicious memory count
   - latency
   - trace_id
9. Add tests:
   - retrieval respects username
   - retrieval respects runtime_id
   - retrieval respects chat_id where requested
   - expired memory excluded
   - conflicted memory penalized
   - suspicious instruction memory not injected as instruction
   - token budget enforced
   - fallback to legacy on Memory V3 failure
   - no secret leakage in context pack
10. Add docs/enterprise_refactor/05_memory_v3_retrieval.md.

Acceptance criteria:
- Existing chat remains unchanged when flag false.
- Memory V3 retrieval works in tests when flag true.
- No leakage across user/runtime/chat.
- Compile and tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 3: memory v3 retrieval and grounding
```

---

# PROMPT 4 — Chat V2: Streaming, History, Sessions, Branching, and Attachments

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Refactor and harden chat backend behavior for enterprise-grade reliability while preserving existing chat APIs.

Hard constraints:
- KURO_CHAT_V2_ENABLED defaults false.
- Existing /api/chat and /api/chat/stream must continue working.
- Preserve SSE contract.
- Do not delete existing chat history.
- All migrations idempotent.
- No external API calls in tests.

Target:
Improve:
- streaming chat
- resumable SSE
- chat history pagination
- message versioning
- edit/regenerate lineage
- attachments continuity
- chat-level settings
- model/provider preferences per session
- traceability
- robust error handling

Tasks:
1. Create kuro_backend/chat_v2/ package:
   - __init__.py
   - schemas.py
   - service.py
   - streaming.py
   - history.py
   - session_settings.py
   - attachments.py
   - telemetry.py
2. Add idempotent chat DB migrations:
   - chat_sessions.model_alias
   - chat_sessions.provider_alias
   - chat_sessions.temperature
   - chat_sessions.runtime_id
   - chat_sessions.workspace_id
   - chat_sessions.archived_at
   - chat_sessions.deleted_at
   - chat_history.trace_id
   - chat_history.event_seq
   - chat_history.parent_message_id
   - chat_history.branch_id
   - chat_history.artifact_refs_json
   - chat_history.grounding_refs_json
3. Implement ChatSessionSettings:
   - provider_alias
   - model_alias
   - temperature
   - runtime_id
   - mode: default/research/agent/market/qa
   - tools_enabled
   - web_search_enabled
   - memory_v3_enabled
4. Add backend APIs:
   - GET /api/chats
   - POST /api/chats
   - GET /api/chats/{chat_id}
   - PATCH /api/chats/{chat_id}
   - DELETE /api/chats/{chat_id}
   - GET /api/chats/{chat_id}/messages?before_id=&limit=
   - POST /api/chats/{chat_id}/messages/{message_id}/edit
   - POST /api/chats/{chat_id}/messages/{message_id}/regenerate
   - POST /api/chats/{chat_id}/settings
   Existing routes may delegate into these when KURO_CHAT_V2_ENABLED=true.
5. Implement StreamingEnvelope:
   SSE events:
   - trace
   - token
   - tool_call_start
   - tool_call_delta
   - tool_call_end
   - memory_context
   - structured_output
   - error
   - done
6. Implement resumable SSE:
   - event_seq monotonic per chat stream
   - small in-memory replay buffer
   - honor Last-Event-ID when available
   - fallback gracefully if buffer expired
7. Implement deterministic stream termination:
   - always emits done unless client disconnects
   - explicit error event on exceptions
   - no hanging generator
8. Attachment continuity:
   - keep existing uploaded file behavior
   - add artifact_refs_json to message metadata
   - do not expose raw server paths
   - owner check required
9. Add tests:
   - legacy stream still works when flag false
   - Chat V2 stream emits done
   - error path emits error and done
   - Last-Event-ID replay works
   - chat settings persist
   - pagination works
   - editing creates version lineage
   - regeneration preserves parent_message_id
   - attachment refs do not leak raw path
   - user cannot access another user's chat
10. Add docs/enterprise_refactor/06_chat_v2.md.

Acceptance criteria:
- Backward compatible.
- SSE stable.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 4: chat v2 streaming and history
```

---

# PROMPT 5 — Provider and Model Registry V2

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Implement a provider/model registry that can support Gemini, OpenAI, Anthropic, DeepSeek, and future providers without breaking existing Gemini behavior.

Hard constraints:
- KURO_PROVIDER_REGISTRY_V2_ENABLED defaults false.
- Existing Gemini path remains default.
- Do not replace legacy streaming unless provider registry is enabled and tests pass.
- Provider keys are optional.
- Missing provider key must disable provider gracefully.
- Do not hardcode model IDs beyond env-configurable defaults.
- No real external provider calls in tests.

Target model aliases:
- gemini_fast -> env KURO_MODEL_GEMINI_FAST default gemini-3-flash-preview
- openai_nano -> env KURO_MODEL_OPENAI_NANO default gpt-5.4-nano
- claude_fast -> env KURO_MODEL_CLAUDE_FAST default claude-haiku-4-5
- deepseek_fast -> env KURO_MODEL_DEEPSEEK_FAST default deepseek-v4-flash

Treat these as aliases. Actual API model ID must be read from env and validated lazily.

Tasks:
1. Create kuro_backend/providers/ package:
   - __init__.py
   - schemas.py
   - registry.py
   - router.py
   - base.py
   - gemini_provider.py
   - openai_provider.py
   - anthropic_provider.py
   - deepseek_provider.py
   - errors.py
   - usage.py
   - streaming.py
2. Define ProviderRequest:
   - messages
   - system_instruction
   - model_alias
   - model_id
   - temperature
   - max_output_tokens
   - tools
   - structured_output_schema
   - metadata
   - trace_id
3. Define ProviderResponse:
   - provider
   - model_id
   - content
   - structured
   - raw
   - usage
   - latency_ms
   - finish_reason
   - safety
   - grounding
   - trace_id
4. Define ProviderStreamEvent:
   - event_type
   - delta
   - content
   - tool_call
   - usage
   - raw
   - error
   - done
   - trace_id
5. Implement provider registry:
   - get_enabled_providers()
   - get_model_aliases()
   - resolve_model_alias()
   - get_provider_for_alias()
   - health_check()
6. Implement provider adapters:
   - Gemini adapter can wrap existing google-genai code where safe.
   - OpenAI adapter should use OpenAI SDK only if installed; otherwise disabled gracefully.
   - Anthropic adapter should use Anthropic SDK only if installed; otherwise disabled gracefully.
   - DeepSeek adapter should support OpenAI-compatible HTTP style only if configured; otherwise disabled gracefully.
7. If SDK dependencies are missing:
   - Do not break import.
   - Provider status should show unavailable_dependency.
8. Implement fallback routing:
   - primary alias
   - fallback aliases
   - timeout
   - retry policy
   - no retry on safety refusal unless explicitly safe
9. Add admin-only route:
   - GET /api/admin/providers
   - GET /api/admin/providers/health
10. Add public-safe route:
   - GET /api/models
   Return only enabled aliases and display names, not secrets.
11. Integrate with Chat V2 only when both KURO_CHAT_V2_ENABLED=true and KURO_PROVIDER_REGISTRY_V2_ENABLED=true.
12. Tests:
   - provider registry disabled by default
   - missing keys do not break startup
   - missing SDK does not break startup
   - model aliases resolve from env
   - public models route safe
   - admin provider health requires admin
   - mocked provider generate works
   - mocked provider stream works
   - fallback provider works
   - legacy Gemini path still active when flag false
13. Add docs/enterprise_refactor/07_provider_registry_v2.md.

Acceptance criteria:
- Existing Gemini behavior preserved.
- Provider registry available but optional.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 5: provider and model registry v2
```

---

# PROMPT 6 — Tool Runtime V2: Web Search, Deep Research, Agent Mode, Tasks, and Reminders

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Create a governed tool runtime for ChatGPT-like capabilities:
- Web Search
- Deep Research
- Create Task
- Agent Mode
- Reminder
- tool approval and audit

Hard constraints:
- KURO_AGENT_TOOLS_V2_ENABLED defaults false.
- KURO_WEB_SEARCH_V2_ENABLED defaults false.
- KURO_DEEP_RESEARCH_V2_ENABLED defaults false.
- KURO_TASKS_V2_ENABLED defaults false.
- Do not resurrect old purged habits/reminders code directly.
- Do not allow destructive tools without explicit admin/user approval.
- No real external API calls in tests.
- Do not bypass existing OpenClaw safety checks.

Target:
Implement a new clean tool runtime layer that can orchestrate existing Serper, OpenClaw, ingestion, export, Market Sentinel, and future provider-native tools.

Tasks:
1. Create kuro_backend/tools_v2/ package:
   - __init__.py
   - schemas.py
   - registry.py
   - policy.py
   - executor.py
   - approvals.py
   - audit.py
   - web_search.py
   - deep_research.py
   - tasks.py
   - reminders.py
   - agent_mode.py
2. Tool schema:
   - tool_id
   - display_name
   - description
   - category
   - risk_level: low/medium/high/critical
   - requires_approval
   - requires_admin
   - allowed_runtime_ids
   - allowed_roles
   - input_schema
   - output_schema
   - timeout_s
   - budget_cost
   - enabled_flag
3. Implement ToolPolicy:
   - can_list_tool
   - can_execute_tool
   - requires_approval
   - validate_input
   - enforce_runtime_boundary
   - enforce_rate_limit if available
4. Implement ToolExecutor:
   - execute tool by tool_id
   - structured result
   - trace_id
   - timeout
   - safe error
   - audit log
5. Implement Web Search tool:
   - Use existing serper_tool where configured.
   - Optional provider-native search can be wired later.
   - Return normalized sources:
     title, url, snippet, source_type, published_at, retrieved_at, confidence.
   - Do not hallucinate citations.
6. Implement Deep Research V2 as a Kuro-native background research job:
   - planning step
   - search step
   - source collection
   - source reliability scoring
   - synthesis
   - citation/provenance output
   - exportable report
   - job status
   - no dependency on ChatGPT Deep Research product unless future provider adapter supports it
7. Implement Tasks V2:
   - New DB table tasks_v2
   - task_id
   - username
   - workspace_id
   - title
   - description
   - status
   - due_at
   - recurrence_rule
   - source_chat_id
   - source_message_id
   - created_at
   - updated_at
   - completed_at
   - metadata_json
8. Implement Reminders V2:
   - New DB table reminders_v2
   - reminder_id
   - task_id nullable
   - username
   - channel: web/telegram/both
   - remind_at
   - status
   - attempt_count
   - last_error
   - created_at
   - sent_at
9. Implement Agent Mode:
   - limited multi-step planning loop
   - max steps env KURO_AGENT_MAX_STEPS default 5
   - tool calls require policy
   - high-risk actions require approval
   - no shell/system commands unless routed through existing safe OpenClaw bridge and explicitly allowed
   - produces traceable plan/result
10. Add APIs:
   - GET /api/tools
   - POST /api/tools/{tool_id}/execute
   - POST /api/deep-research/jobs
   - GET /api/deep-research/jobs/{job_id}
   - GET /api/deep-research/jobs
   - POST /api/tasks
   - GET /api/tasks
   - PATCH /api/tasks/{task_id}
   - DELETE /api/tasks/{task_id}
   - POST /api/reminders
   - GET /api/reminders
   - PATCH /api/reminders/{reminder_id}
11. Add tests:
   - tools disabled by default
   - tool list safe
   - high-risk tool requires approval
   - web search mocked
   - deep research mocked job lifecycle
   - task create/list/update/delete
   - reminder create/list/update
   - no cross-user task access
   - agent mode max steps enforced
   - OpenClaw bridge safety not bypassed
12. Add docs/enterprise_refactor/08_tools_v2.md.

Acceptance criteria:
- Existing legacy 410 behavior for old removed endpoints remains unless intentionally superseded by new clean V2 endpoints.
- No external calls in tests.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 6: governed tools, research, tasks, and agent mode
```

---

# PROMPT 7 — Market Sentinel V2

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Refactor Market Sentinel into a faster, more adaptive, multi-source market intelligence engine with source grounding, freshness checks, deduplication, and auditability.

Hard constraints:
- KURO_MARKET_SENTINEL_V2_ENABLED defaults false.
- Do not break current Market Sentinel.
- Do not execute trades.
- Do not provide guaranteed financial advice.
- No real external API calls in tests.
- External API failures must degrade gracefully.
- OpenClaw must be called through existing bridge safety/circuit breaker.

Target:
Market Sentinel V2 should triangulate:
- quantitative price data
- qualitative news
- market/company catalysts
- macro signals
- local watchlist
- OpenClaw market_analysis
- Google/Gemini grounding if configured
- Serper/news if configured
- existing yfinance/Stooq-style sources if present
- user watchlist and prediction_watch data

Tasks:
1. Create kuro_backend/market_v2/ package:
   - __init__.py
   - schemas.py
   - source_registry.py
   - collectors.py
   - normalizer.py
   - analyzer.py
   - triangulator.py
   - freshness.py
   - alerts.py
   - cache.py
   - telemetry.py
   - routes.py
2. Define schemas:
   - MarketSource
   - MarketObservation
   - PriceObservation
   - NewsObservation
   - GroundingObservation
   - MarketSignal
   - MarketSentinelReport
   - MarketAlert
   - SourceReliabilityScore
3. Source registry:
   - price_yfinance if current repo uses it
   - price_stooq if current repo uses it
   - openclaw_market_analysis
   - serper_news
   - gemini_google_grounding if configured
   - manual_watchlist
   - finance_db snapshots
4. Implement normalization:
   - symbol
   - exchange
   - observed_at
   - source_id
   - source_url nullable
   - value_json
   - confidence_score
   - freshness_seconds
   - retrieval_latency_ms
5. Implement triangulation:
   - price movement
   - news sentiment/catalyst
   - volume if available
   - contradiction detection
   - stale data detection
   - source agreement score
   - confidence score
   - "insufficient evidence" result if weak
6. Implement adaptive collection:
   - if price moves beyond threshold, fetch more news
   - if news conflict detected, fetch additional source
   - if source stale, downgrade confidence
   - if OpenClaw unavailable, continue with other sources
7. Implement report:
   - concise summary
   - evidence table
   - source list
   - freshness warnings
   - confidence
   - "not financial advice" footer
   - no buy/sell certainty unless explicitly phrased as watchlist signal with uncertainty
8. Implement alerts:
   - deduplicate fingerprint
   - TTL
   - severity
   - channel: dashboard/telegram
   - dead-letter if Telegram fails
9. Add APIs:
   - GET /api/market-v2/watchlist
   - POST /api/market-v2/watchlist
   - DELETE /api/market-v2/watchlist/{symbol}
   - POST /api/market-v2/analyze
   - GET /api/market-v2/snapshot
   - GET /api/market-v2/alerts
   - GET /api/admin/market-v2/health
10. Add scheduler only if flag true:
   - Do not run V2 sentinel when disabled.
   - Avoid duplicate schedulers.
11. Integrate with Memory V3 if enabled:
   - Store market_signal_memory with TTL.
   - Do not pollute user semantic memory with transient market signals.
12. Add tests:
   - Market V2 disabled by default
   - mocked source collection
   - OpenClaw failure fallback
   - stale source downgraded
   - contradictory signals produce low confidence
   - no trade execution API exists
   - alert dedup works
   - Telegram DLQ works with market alert
   - no cross-user watchlist access
   - market_signal_memory TTL if Memory V3 enabled
13. Add docs/enterprise_refactor/09_market_sentinel_v2.md.

Acceptance criteria:
- Current Market Sentinel remains intact when flag false.
- V2 produces grounded report from mocked sources.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 7: market sentinel v2
```

---

# PROMPT 8 — Telegram API V2

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Upgrade Telegram integration into a robust inbound/outbound API bridge with retries, DLQ, command routing, and chat runtime integration.

Hard constraints:
- KURO_TELEGRAM_V2_ENABLED defaults false.
- Existing Telegram notifications must keep working.
- Do not expose Telegram token.
- Validate webhook secret.
- No real Telegram calls in tests.
- Telegram inbound must follow the same runtime/memory/tool boundaries as web chat.

Tasks:
1. Create kuro_backend/telegram_v2/ package:
   - __init__.py
   - schemas.py
   - notifier.py
   - inbound.py
   - commands.py
   - queue.py
   - dlq.py
   - security.py
   - routes.py
2. Implement outbound queue:
   - message_id
   - username
   - chat_id/channel
   - payload_json
   - status
   - attempt_count
   - next_retry_at
   - last_error
   - created_at
   - sent_at
3. Implement DLQ:
   - failed messages after max attempts
   - admin retry endpoint
   - admin inspect endpoint
4. Implement inbound webhook:
   - POST /api/telegram/webhook
   - validate TELEGRAM_WEBHOOK_SECRET or configured header/token
   - parse incoming Telegram message
   - map Telegram sender to Kuro username using admin-controlled mapping
   - reject unknown sender by default
5. Implement commands:
   - /start
   - /help
   - /status
   - /chat <message>
   - /research <topic>
   - /market <symbol>
   - /task <title>
   - /remind <time> <text>
6. Telegram inbound chat:
   - Use same chat service/runtime core as web chat.
   - Do not bypass Memory V3 policy.
   - Do not bypass tool policy.
   - Use safe default runtime_id.
7. Add admin APIs:
   - GET /api/admin/telegram-v2/health
   - GET /api/admin/telegram-v2/dlq
   - POST /api/admin/telegram-v2/dlq/{id}/retry
   - GET /api/admin/telegram-v2/mappings
   - POST /api/admin/telegram-v2/mappings
8. Add tests:
   - Telegram V2 disabled by default
   - webhook rejects missing secret
   - unknown sender rejected
   - known sender command parsed
   - outbound retry scheduled on failure
   - DLQ after max attempts
   - admin routes require admin
   - /market command uses mocked Market V2
   - /research command uses mocked Deep Research V2
   - /task and /remind create mocked V2 task/reminder
9. Add docs/enterprise_refactor/10_telegram_v2.md.

Acceptance criteria:
- Existing Telegram notifier not broken.
- V2 is safe and disabled by default.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 8: telegram api v2
```

---

# PROMPT 9 — Overall API and Middleware Hardening

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Harden the overall FastAPI API and middleware layer for enterprise readiness.

Hard constraints:
- KURO_API_V2_ENABLED defaults false.
- Existing routes must remain compatible.
- Do not expose internal config/secrets.
- Do not weaken auth.
- Do not break SSE.

Tasks:
1. Create kuro_backend/api_v2/ package:
   - __init__.py
   - schemas.py
   - responses.py
   - errors.py
   - middleware.py
   - authz.py
   - rate_limit.py
   - pagination.py
   - openapi.py
2. Standardize response envelopes:
   - success
   - error
   - trace_id
   - data
   - meta
3. Standardize error codes:
   - unauthorized
   - forbidden
   - not_found
   - validation_error
   - feature_disabled
   - rate_limited
   - provider_unavailable
   - tool_denied
   - memory_denied
   - internal_error
4. Middleware:
   - trace_id
   - request timing
   - request size limit
   - security headers
   - CORS sanity
   - rate limit hooks
   - exception normalization
5. RBAC/AuthZ:
   - admin
   - user
   - auditor
   - service_account
   - future workspace roles
   Use existing user registry/auth where possible. Do not invent insecure auth.
6. Rate limits:
   - per user
   - per IP
   - per route class
   - separate limits for chat, market, research, Telegram
   Keep disabled or permissive by default unless configured.
7. Add API versioning strategy:
   - existing routes stay
   - new routes may live under /api/v2 where useful
   - do not duplicate everything unnecessarily
8. OpenAPI:
   - ensure new schemas are documented
   - hide admin-only internals from public UI if possible
9. Add tests:
   - trace_id header exists
   - standardized error response
   - admin route forbidden for non-admin
   - rate limit mocked
   - request size limit mocked
   - feature disabled error shape
   - existing chat route still works
10. Add docs/enterprise_refactor/11_api_middleware_v2.md.

Acceptance criteria:
- Existing API behavior preserved.
- Middleware does not break streaming.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 9: api and middleware hardening
```

---

# PROMPT 10 — Frontend V2 ChatGPT-Like UI/UX Refactor

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Refactor the frontend UX toward a ChatGPT-like agent window while preserving current dashboard functionality.

Hard constraints:
- KURO_FRONTEND_V2_ENABLED defaults false.
- Do not remove existing frontend unless replaced safely.
- Do not copy ChatGPT branding, logos, names, or proprietary visual identity.
- Implement similar interaction patterns, not branding.
- Keep admin-only controls protected both frontend and backend.
- If frontend JS is currently Vanilla JS + Jinja, do not introduce React/Vue unless the repo already supports it or the change is explicitly scoped and tested.

Target UX:
- Left sidebar focuses on chats/sessions.
- Admin/sidebar tools move into top-right profile menu.
- Profile menu contains "Administration Settings".
- Administration Settings contains:
  - System Status
  - Storage Health
  - Memory V3
  - Provider/Model Settings
  - AI Temperature
  - Runtime Settings
  - Market Sentinel
  - Ingestion Center
  - Evaluation
  - Backup
  - Telegram
  - Feature Flags
- Main chat resembles modern conversational UI:
  - session list
  - new chat
  - search chats
  - pinned chats
  - message actions
  - copy/edit/regenerate/bookmark/export
  - model selector
  - temperature control
  - web search toggle
  - deep research button
  - agent mode toggle
  - create task/reminder buttons
  - streaming token display
  - error recovery
  - citation/source drawer
  - memory/source transparency drawer

Tasks:
1. Audit current:
   - web_interface/templates/index.html
   - web_interface/static/js/app.js
   - CSS files
2. Create feature-flagged frontend V2 entry:
   - If flag false: current UI.
   - If flag true: V2 layout.
3. Prefer modular JS organization:
   - web_interface/static/js/v2/api.js
   - web_interface/static/js/v2/chat.js
   - web_interface/static/js/v2/sidebar.js
   - web_interface/static/js/v2/profile_menu.js
   - web_interface/static/js/v2/admin_settings.js
   - web_interface/static/js/v2/streaming.js
   - web_interface/static/js/v2/model_settings.js
   - web_interface/static/js/v2/tasks.js
   - web_interface/static/js/v2/market.js
4. CSS:
   - add web_interface/static/css/v2.css or modular equivalent
   - responsive layout
   - accessible contrast
   - mobile-friendly sidebar collapse
5. Admin Settings:
   - rendered only for admin
   - backend still enforces admin
   - non-admin must not see admin menu
   - direct URL access still forbidden by backend
6. Model/temperature settings:
   - use /api/models and chat settings endpoints
   - do not expose raw API keys
   - store per-session settings
7. ChatGPT-like features:
   - Web Search toggle calls tool runtime when enabled
   - Deep Research opens job creation panel
   - Create Task creates task from current message or manual input
   - Agent Mode toggles governed agent loop
   - Reminder creates V2 reminder
   - all unavailable features show disabled UI state with explanation
8. Streaming:
   - support token events
   - support tool events
   - support memory/source events
   - support error/done
   - reconnect/backoff where appropriate
9. Chat history:
   - cursor pagination
   - search
   - pinned chats
   - rename
   - archive/delete
10. Add tests:
   - index renders current UI when flag false
   - index renders V2 markers when flag true
   - non-admin does not see Administration Settings
   - admin sees Administration Settings
   - static JS files served
   - no raw secret values appear in HTML
   - chat settings panel uses safe model aliases
11. Add docs/enterprise_refactor/12_frontend_v2.md.

Acceptance criteria:
- Current UI not broken when flag false.
- V2 UI available when flag true.
- Admin controls moved into profile menu in V2.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 10: frontend v2 chat ux
```

---

# PROMPT 11 — Enterprise Observability, Evaluation, and Security Governance

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Strengthen observability, evaluation, auditability, and AI security governance across Kuro.

Hard constraints:
- KURO_ENTERPRISE_OBSERVABILITY_ENABLED defaults false where new behavior could be noisy.
- Preserve existing Phoenix/OpenTelemetry behavior.
- Do not log secrets.
- Do not log full sensitive prompts unless already explicitly configured.
- Do not expose traces to non-admin users.

Tasks:
1. Create kuro_backend/enterprise_observability/ package:
   - __init__.py
   - schemas.py
   - trace_exporter.py
   - metrics.py
   - audit.py
   - evals.py
   - security_events.py
   - dashboards.py
2. Align trace attributes with:
   - OpenTelemetry GenAI conventions where practical
   - OpenInference-style span categories where practical
3. Track:
   - chat latency
   - provider latency
   - provider errors
   - token usage
   - memory retrieval latency
   - memory write latency
   - memory conflict count
   - tool calls
   - tool denials
   - market source freshness
   - Telegram DLQ
   - SSE disconnects
   - structured output validity
   - hallucination/evaluation score if existing evaluator supports it
4. Add audit event model:
   - event_id
   - event_type
   - actor_username
   - actor_role
   - workspace_id
   - runtime_id
   - chat_id
   - resource_type
   - resource_id
   - action
   - result
   - trace_id
   - created_at
   - metadata_json
5. AI security event types:
   - prompt_injection_detected
   - memory_poisoning_suspected
   - tool_denied
   - excessive_agency_blocked
   - sensitive_info_blocked
   - cross_runtime_access_attempt
   - cross_user_access_attempt
   - provider_error
   - schema_validation_failed
6. Add admin APIs:
   - GET /api/admin/observability/summary
   - GET /api/admin/observability/traces
   - GET /api/admin/observability/security-events
   - GET /api/admin/observability/evals
   - GET /api/admin/observability/market
   - GET /api/admin/observability/memory
7. Add evaluation enhancements:
   - Memory retrieval quality smoke eval
   - SSE contract eval
   - Market Sentinel source quality eval
   - Provider fallback eval
   - Boundary leakage eval
8. Tests:
   - observability routes require admin
   - traces do not contain secrets
   - security event persisted
   - memory conflict metric increments
   - tool denial event logged
   - provider fallback event logged
   - SSE disconnect counted
9. Add docs/enterprise_refactor/13_observability_security.md.

Acceptance criteria:
- Existing observability not broken.
- New observability is admin-only.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 11: enterprise observability and governance
```

---

# PROMPT 12 — Deployment, Secrets, Backup, and Enterprise Ops

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Prepare Kuro for small enterprise/startup deployment with safer operations, environment profiles, backups, and secrets hygiene.

Hard constraints:
- Do not require Kubernetes.
- Do not break local dev.
- Do not commit secrets.
- Do not delete existing certs/config unless unsafe and documented.
- Keep changes practical for small enterprise deployment.

Tasks:
1. Add deployment profiles:
   - local-dev
   - single-vm
   - docker-compose
   - staging
   - enterprise-pilot
2. Create docs/deployment/:
   - local_dev.md
   - single_vm.md
   - docker_compose.md
   - staging.md
   - enterprise_pilot.md
   - secrets.md
   - backup_restore.md
   - monitoring.md
   - incident_response.md
3. Add or update .env.example:
   - all provider keys
   - Telegram
   - Serper
   - OpenClaw
   - DB paths
   - feature flags
   - model aliases
   - security settings
   - backup settings
4. Add startup validation:
   - warns on missing optional provider keys
   - fails only on required local settings
   - does not print secret values
5. Add backup verification:
   - manual backup route already exists if present
   - add restore verification docs
   - add backup health checks if feasible
6. Add docker-compose if not present:
   - app
   - optional phoenix
   - optional volume mounts
   - do not include real secrets
7. Add health endpoints if missing:
   - /api/health
   - /api/ready
   - /api/live
   Keep public-safe.
8. Add tests:
   - .env.example contains required keys
   - startup validation masks secrets
   - health endpoint safe
   - backup docs exist
   - deployment docs exist
9. Add docs/enterprise_refactor/14_deployment_ops.md.

Acceptance criteria:
- Local dev still works.
- No secrets committed.
- Tests pass:
  python -m compileall kuro_backend main.py
  pytest tests/ -x --tb=short

Commit message:
Enterprise Refactor Phase 12: deployment and enterprise ops
```

---

# PROMPT 13 — Performance, Bug Fixing, and Critical Path Sweep

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Run a critical bug-fixing and performance sweep after the major enterprise refactor.

Hard constraints:
- Do not add new major features.
- Focus on stability, performance, correctness, and test coverage.
- Do not delete user data.
- Do not remove existing routes without compatibility handling.

Tasks:
1. Search for:
   - pass in production code
   - TODO in production code
   - FIXME in production code
   - NotImplementedError
   - placeholder return values
   - broad except without logging
   - direct print of secrets
   - raw API key exposure
   - unbounded loops
   - unbounded retries
   - missing timeouts
   - external HTTP calls without timeout
   - DB writes without migration/history pattern
2. Fix critical issues found.
3. Add tests for each fix.
4. Performance review:
   - chat streaming hot path
   - memory retrieval path
   - Mem0/Chroma retrieval
   - semantic cache invalidation
   - Market Sentinel source collection
   - Telegram queue
   - frontend initial load
5. Add lightweight timing metrics where missing.
6. Ensure:
   - Memory V3 disabled path is fast
   - Provider registry disabled path is fast
   - Chat V2 disabled path is fast
   - feature flag checks do not add heavy overhead
7. Run full tests:
   python -m compileall kuro_backend main.py
   pytest tests/ -x --tb=short
8. Create docs/enterprise_refactor/15_performance_bugfix_report.md:
   - issues found
   - issues fixed
   - issues deferred
   - performance risks
   - next recommendations

Acceptance criteria:
- No production placeholder paths remain.
- Tests pass.
- Critical bugs fixed.
- Report exists.

Commit message:
Enterprise Refactor Phase 13: performance and critical bugfix sweep
```

---

# PROMPT 14 — Documentation, SYSTEM_MAP, Enterprise Acceptance Report

## Paste to Codex

```text
You are working on the Kuro AI repository.

Goal:
Finalize documentation after the enterprise refactor.

Hard constraints:
- Do not modify functional code unless needed to fix broken docs references.
- Do not claim features are production-ready if they are feature-flagged or partial.
- Be honest about disabled features and remaining risks.

Tasks:
1. Update SYSTEM_MAP.md:
   - new packages
   - new routes
   - new env vars
   - new DB tables
   - new feature flags
   - new data flows
   - new tests
   - risks/blind spots
2. Create docs/enterprise_refactor/16_final_acceptance_report.md.
3. Include:
   - completed phases
   - feature flags
   - default enabled/disabled status
   - enterprise readiness estimate
   - small enterprise pilot readiness
   - large enterprise blockers
   - rollback instructions
   - remaining risks
   - next roadmap
4. Create docs/enterprise_refactor/17_codex_execution_summary.md:
   - prompt executed
   - files changed
   - tests added
   - migrations added
   - known limitations
5. Create docs/enterprise_refactor/18_next_improvement_backlog.md with priorities:
   P0:
   - Memory V3 production rollout
   - Chat V2 rollout
   - Provider registry integration
   - Market Sentinel V2 pilot
   - UI V2 admin settings
   - Security/RBAC hardening
   P1:
   - PostgreSQL/pgvector migration option
   - Workspace/tenant isolation
   - SSO/OIDC
   - OpenTelemetry collector
   - Deep Research V2 improvements
   P2:
   - Enterprise onboarding
   - compliance packs
   - customer-facing documentation
   - advanced model evaluation
6. Run:
   python -m compileall kuro_backend main.py
   pytest tests/ -x --tb=short

Acceptance criteria:
- SYSTEM_MAP updated accurately.
- Final acceptance report exists.
- Execution summary exists.
- Backlog exists.
- Tests pass.

Commit message:
Enterprise Refactor Phase 14: documentation and acceptance report
```

---

# 4. Execution Gates

Use these stop gates. Do not continue if a gate fails.

## Gate A — Foundation

After Prompts -2, -1, 0, 1:

```text
Must pass:
- backup exists
- storage health route works
- feature flags default off
- current chat still works
- public capabilities safe
```

## Gate B — Memory

After Prompts 2 and 3:

```text
Must pass:
- Memory V3 disabled by default
- Memory V3 init idempotent
- no user/runtime leakage
- context pack no secrets
- existing memory path unchanged when flag false
```

## Gate C — Chat and Provider

After Prompts 4 and 5:

```text
Must pass:
- legacy SSE still works
- Chat V2 SSE done/error events work
- provider registry missing keys do not break startup
- provider router not used unless enabled
```

## Gate D — Tools, Market, Telegram

After Prompts 6, 7, 8:

```text
Must pass:
- tools disabled by default
- high-risk tools require approval
- market report does not claim certainty
- Telegram webhook validates secret
- no real external calls in tests
```

## Gate E — UI and Enterprise Ops

After Prompts 9, 10, 11, 12:

```text
Must pass:
- admin settings hidden from non-admin
- admin backend still enforces access
- trace_id exists
- secrets not logged
- deployment docs exist
```

## Gate F — Final

After Prompts 13 and 14:

```text
Must pass:
- no production placeholders
- SYSTEM_MAP updated
- final acceptance report exists
- tests pass
```

---

# 5. Improvements to Prioritize After This Refactor

These are not all blockers for the first enterprise pilot, but they should enter the next roadmap.

```text
P0 — critical next improvements:
1. Memory V3 production rollout with staged migration from legacy stores.
2. Workspace/tenant isolation: workspace_id + user_id + runtime_id + chat_id as standard scope.
3. RBAC permissions model beyond admin/non-admin.
4. Provider registry production rollout with real streaming adapters.
5. Chat V2 full rollout.
6. Market Sentinel V2 reliability validation with real source comparison.
7. UI V2 usability test.
8. Security audit for prompt injection, memory poisoning, excessive agency, and tool misuse.

P1 — enterprise maturity:
1. PostgreSQL + pgvector migration option.
2. SSO/OIDC.
3. OpenTelemetry collector deployment.
4. Secrets manager integration.
5. Audit log export.
6. Data retention and deletion workflow.
7. Deep Research source quality scoring.
8. Evaluation benchmark suite.

P2 — productization:
1. Customer onboarding workflow.
2. Small enterprise deployment template.
3. Admin manual.
4. User manual.
5. Compliance pack.
6. Pricing/usage dashboard.
7. Support/incident runbook.
```

---

# 6. Memory V3 — Conceptual Architecture Summary

Use this as the architectural north star when reviewing Codex output.

```text
Memory input
  -> scope validation
  -> event append
  -> candidate extraction
  -> canonicalization
  -> sensitivity classification
  -> deduplication
  -> conflict detection
  -> retention assignment
  -> canonical memory upsert
  -> embedding/ref update
  -> telemetry/audit

Memory retrieval
  -> scope validation
  -> query analysis
  -> keyword retrieval
  -> semantic retrieval
  -> recent/high-importance retrieval
  -> policy filtering
  -> conflict filtering
  -> anti-poisoning check
  -> ranking
  -> token-budget context packing
  -> provenance/citation attachment
  -> telemetry/audit
```

Do not allow memory to become a single unstructured vector bucket. The source of truth should be canonical relational/provenance records; vector recall is an index, not truth.

---

# 7. Market Sentinel V2 — Conceptual Architecture Summary

```text
watchlist / request
  -> source registry
  -> quantitative collection
  -> qualitative collection
  -> grounding/news collection
  -> freshness scoring
  -> contradiction detection
  -> source agreement scoring
  -> triangulated market signal
  -> confidence + uncertainty notes
  -> alert dedup
  -> dashboard/telegram delivery
  -> market_signal_memory TTL write if enabled
```

Never claim certainty. Always include source freshness and confidence.

---

# 8. UI V2 — Conceptual Architecture Summary

```text
Left sidebar:
- new chat
- chat search
- pinned chats
- recent sessions
- market/research/task shortcuts if enabled

Top right profile:
- user profile
- model settings
- temperature
- runtime mode
- Administration Settings
- logout

Administration Settings:
- system status
- storage
- memory
- providers
- market
- Telegram
- ingestion
- evaluation
- feature flags
- backup
```

The UI should feel familiar and efficient, but must not copy proprietary branding.

---

# 9. Final Reminder for Codex

```text
This is a major refactor. Prefer additive, reversible changes.
Keep flags off by default.
Keep legacy behavior safe.
Tests are mandatory.
No secret leakage.
No fake implementation.
No financial certainty.
No destructive autonomous tools.
```
