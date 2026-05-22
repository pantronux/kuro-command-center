# Enterprise Gap Matrix

Date: 2026-05-22
Scope: Prompt -2 enterprise readiness gap inventory. This file intentionally documents gaps only; it does not prescribe code changes beyond the prompt pack phases.

## Gap Summary

The matrix below identifies more than 20 enterprise gaps and maps each to the next refactor phase in `KuroAI_Enterprise_Major_Refactor_Codex_Prompts.md`.

| ID | Domain | Gap | Current evidence path | Risk | Proposed phase | Blocker |
|---|---|---|---|---|---|---|
| G-001 | Control plane | No master enterprise feature flag layer for the upcoming refactor. | `kuro_backend/config.py`, `main.py` | New features could accidentally alter default behavior. | Prompt 0 | Yes |
| G-002 | API | No public-safe `/api/capabilities` route. | `main.py` | Clients cannot discover safe high-level feature availability without internal knowledge. | Prompt 0 | Yes |
| G-003 | API | No versioned `/api/v1` contract boundary. | `main.py` | Refactors may break current routes or make deprecation hard. | Prompt 9 | Yes |
| G-004 | Middleware | Request context is only trace-centric, not tenant/runtime/auth/flag aware. | `main.py` `TraceMiddleware` | Logs, DB writes, tools, and memory reads may lack consistent correlation. | Prompt 9 | Yes |
| G-005 | Auth/RBAC | Admin access is username equality against `ADMIN_USERNAME`. | `main.py`, `telegram_center/auth.py` | Not enterprise-grade role/claim mapping. | Prompt 9, 11 | Yes |
| G-006 | Tenancy | No first-class tenant/workspace context across APIs. | `main.py`, `memory_manager.py`, `finance_db.py`, `chat_history.py` | Cross-tenant isolation cannot be proven beyond username filters. | Prompt 2, 9 | Yes |
| G-007 | Storage | No central data catalog for logical stores. | `kuro_backend/db_utils.py`, `SYSTEM_MAP.md` | DB ownership, PII level, backup tier, and retention are not queryable. | Prompt 1 | Yes |
| G-008 | Storage | Migrations are module-local and run at import/bootstrap time. | `chat_history.py`, `memory_manager.py`, `finance_db.py`, `ingestion_registry.py` | Hard to rehearse, audit, or roll back migration changes. | Prompt 1 | Yes |
| G-009 | Storage | SQLite remains the default for many operational stores without repository abstraction. | `chat_history.py`, `finance_db.py`, `memory_manager.py` | Future Postgres/pgvector migration is high-friction. | Prompt 1 | Yes |
| G-010 | Memory | Memory source of truth is split across SQLite, Mem0/Qdrant, Chroma, JSON, and in-memory cache. | `memory_coordinator.py`, `memory_manager.py`, `perpetual_memory.py`, `semantic_cache.py` | Provenance, delete/export, and debugging are fragmented. | Prompt 2, 3 | Yes |
| G-011 | Memory | Memory V2 fields extend legacy `short_term` rather than forming a separate governed repository. | `memory_manager.py`, `memory_v2/*` | V2 semantics depend on legacy table lifecycle. | Prompt 2 | Yes |
| G-012 | Memory | Mem0 retrieval filters runtime metadata only after retrieval. | `memory_coordinator.py` `_filter_mem0_results_by_runtime` | Inefficient and harder to prove isolation at storage layer. | Prompt 3 | Yes |
| G-013 | Memory | Legacy Mem0 rows without runtime metadata remain visible to sovereign runtime. | `memory_coordinator.py` | Legacy compatibility may preserve ambiguous memory scope. | Prompt 2, 3 | Yes |
| G-014 | Memory | Master profile JSON is treated as high-authority state outside DB audit and row-level provenance. | `memory_manager.py` | Profile edits are hard to govern/export/delete consistently. | Prompt 2 | Yes |
| G-015 | Memory | Semantic cache is process-local and enabled by default. | `semantic_cache.py` | Multi-worker consistency and tenant-wide invalidation are limited. | Prompt 3, 11 | No |
| G-016 | Chat | SSE replay buffer is process-local per session. | `main.py` `_sse_buffers` | Worker restart or multi-process deployment loses resumability. | Prompt 4 | Yes |
| G-017 | Chat | Stream cancel endpoint only acknowledges client intent. | `main.py` `/api/chat/stream/{request_id}` | Long-running model/tool work may continue server-side. | Prompt 4 | No |
| G-018 | Chat | No idempotency key on chat send or mutating session actions. | `main.py`, `chat_history.py` | Retries can create duplicate effects across chat/memory/tool writes. | Prompt 1, 4 | Yes |
| G-019 | Provider | Legacy provider router flag exists, but provider registry is incomplete for enterprise routing. | `kuro_backend/provider/*`, `playground_runtime/providers/*` | Capability discovery, streaming, retries, and failover are uneven. | Prompt 5 | Yes |
| G-020 | Tools | Tool execution policy exists in pieces, not as a versioned governed tool runtime. | `langgraph_core.py`, `kuro_backend/tools/*`, `openclaw_bridge.py` | High-risk tool access and audit are not centrally enforced. | Prompt 6 | Yes |
| G-021 | Market | Market Sentinel mixes price fetch, LLM/OpenClaw analysis, alerts, and persistence. | `finance_db.py`, `price_ticker_worker.py`, `market_sentinel.py` | Enterprise operators cannot separately audit evidence, models, and publication. | Prompt 7 | No |
| G-022 | Market | `/api/sentinel/latest` route is declared but currently has no implementation body beyond docstring. | `main.py` | API clients can receive `null` for a documented route. | Prompt 7 or Prompt 13 | No |
| G-023 | Telegram | Telegram operational identity maps to admin profile rather than enterprise subjects and roles. | `telegram_center/auth.py`, `telegram_center/service.py` | Hard to audit user intent and action authority. | Prompt 8 | No |
| G-024 | Telegram | Bot lifecycle runs in same deployment process model as FastAPI scheduling. | `main.py`, `telegram_center/service.py` | Production scaling and shutdown behavior are harder to reason about. | Prompt 8, 12 | No |
| G-025 | Frontend | Main dashboard JS is a large single file with many responsibilities. | `web_interface/static/js/app.js` | Risky to evolve ChatGPT-like UX without regressions. | Prompt 10 | No |
| G-026 | Frontend security | Markdown is rendered with `marked.parse`; no obvious DOMPurify/sanitizer dependency in the template. | `index.html`, `app.js` | Model output or stored content may create XSS risk if unsafe HTML is accepted. | Prompt 10, 11 | Yes |
| G-027 | Frontend | Admin-only links are hidden client-side but authorization still relies on backend checks. | `index.html`, `app.js`, `main.py` | UX can hide features but must not be treated as security. | Prompt 10 | No |
| G-028 | Observability | Trace IDs are present, but request_id, runtime_id, provider/model, memory/tool events are not uniformly propagated through all operations. | `main.py`, `langgraph_core.py`, `observability.py` | Incomplete incident reconstruction. | Prompt 11 | Yes |
| G-029 | Observability | Phoenix auth is noted as disabled for local private network. | `main.py`, `observability.py` | Unsafe if deployed beyond trusted network. | Prompt 11, 12 | Yes |
| G-030 | Deployment | No reviewed container/orchestration/runbook layer for app, worker, DB, vector store, and backup restore. | repo root, `requirements.txt`, `SYSTEM_MAP.md` | Enterprise deployment is manual and environment-specific. | Prompt 12 | Yes |
| G-031 | Secrets | `.env` exists locally and `.env.example` is not part of current audited files. | `.env`, `.gitignore` | New operators lack a safe documented env template. | Prompt 0, 12 | Yes |
| G-032 | Tests | Broad tests exist, but no enterprise baseline test file yet. | `tests/` | Refactor gates cannot assert backup/docs/ignore posture yet. | Prompt -1 | No |
| G-033 | Documentation | Enterprise refactor docs were absent before this phase. | `docs/enterprise_refactor/` | Refactor lacks auditable phase records. | Prompt -2, 14 | No |

## Recommended Sequencing

The safest path is the prompt pack order. The deep research report recommends memory-first, but the prompt pack sensibly places safety, flags, and storage before Memory V3. Therefore the immediate next executable phase after this audit should be Prompt -1, not Memory V3 directly.

## Blocker Count

- Blocker gaps: 23
- Non-blocker gaps: 10
- Total gaps listed: 33

