# Kuro Enterprise Refactor Phase -2 Repo Audit

Date: 2026-05-22
Scope: zero-functional-change enterprise readiness audit before major refactor.
Reference inputs: `KuroAI_Enterprise_Major_Refactor_Codex_Prompts.md` and `kuro-deep-research-report.md`.

## Files Reviewed

Required prompt files reviewed:

- `SYSTEM_MAP.md`
- `main.py`
- `kuro_backend/config.py`
- `kuro_backend/langgraph_core.py`
- `kuro_backend/memory_coordinator.py`
- `kuro_backend/memory_manager.py`
- `kuro_backend/perpetual_memory.py`
- `kuro_backend/chat_history.py`
- `kuro_backend/db_utils.py`
- `kuro_backend/telegram_notifier.py`
- `kuro_backend/finance_db.py`
- `kuro_backend/price_ticker_worker.py`
- `kuro_backend/dreaming_worker.py`
- `kuro_backend/execution/openclaw_bridge.py`
- `web_interface/templates/index.html`
- `web_interface/static/js/app.js`

Additional supporting files inspected for inventory completeness:

- `kuro_backend/market_sentinel.py`
- `kuro_backend/semantic_cache.py`
- `kuro_backend/ingestion_center/ingestion_registry.py`
- `kuro_backend/ingestion_center/embedding_manager.py`
- `kuro_backend/ingestion_center/ingestion_manager.py`
- `kuro_backend/telegram_center/auth.py`
- `kuro_backend/telegram_center/service.py`
- `kuro_backend/telegram_center/notifications.py`
- `kuro_backend/telegram_center/actions.py`
- `tests/`

## Executive Assessment

Kuro is an advanced personal AI monolith with many enterprise-shaped subsystems already present: runtime registry, boundary guard, structured output schemas, chat sessions, trace middleware, backup routines, ingestion registry, and Telegram hardening. It is not yet an enterprise platform because the control plane and data plane are still split across several local stores and lightweight authorization conventions.

The strongest near-term sequence remains the prompt pack sequence:

1. Phase -1: safety baseline and backups.
2. Phase 0: enterprise flags and public/admin-safe capabilities.
3. Phase 1: storage foundation.
4. Phase 2/3: Memory V3 core and retrieval.
5. Later phases: chat, providers, tools, market, Telegram, API, frontend, observability, deployment.

This audit intentionally changes no functional code.

## Dimension Audit

| Dimension | Current modules | Current strengths | Current risks | Enterprise gaps | Next phase | Blocker |
|---|---|---|---|---|---|---|
| Backend architecture | `main.py`, `kuro_backend/langgraph_core.py`, `kuro_backend/runtime/*`, `kuro_backend/services/*` | Single deployable FastAPI app; LangGraph orchestration; runtime registry and boundary guard exist; many route-level tests exist. | `main.py` is very large and owns routing, auth helpers, schedulers, uploads, frontend pages, admin checks, and background jobs. | No versioned API boundary; no central request context object; mixed route response envelopes; several subsystems are imported at startup. | Prompt 0, 1, 9 | Blocker |
| Memory architecture | `kuro_backend/memory_coordinator.py`, `kuro_backend/memory_manager.py`, `kuro_backend/perpetual_memory.py`, `kuro_backend/memory_v2/*`, `kuro_backend/semantic_cache.py` | Strong orchestration surface; runtime namespace fields; Mem0 timeout and write-failure recovery; short-term chat_id isolation; ingestion bridge. | Source of truth is split across SQLite, Mem0/Qdrant, Chroma, JSON profile, and in-process cache. | Need Memory V3 repository, typed records, provenance, conflict lifecycle, retention, delete/export, dual-write/shadow-read path. | Prompt 2, 3 | Blocker |
| Storage/database design | `kuro_backend/db_utils.py`, `kuro_backend/chat_history.py`, `kuro_backend/memory_manager.py`, `kuro_backend/finance_db.py`, `kuro_backend/intelligence_db.py`, `kuro_backend/ingestion_center/ingestion_registry.py` | WAL/busy-timeout helper; idempotent column checks in several places; pre-migration snapshots exist; tests redirect DBs. | Store ownership is implicit; schema bootstrap lives in production modules; migrations are module-local and not centrally catalogued. | Need storage package, data catalog, migration history inventory, health checks, retention metadata, backup awareness. | Prompt 1 | Blocker |
| Chat and streaming reliability | `main.py`, `kuro_backend/langgraph_core.py`, `kuro_backend/chat_history.py`, `web_interface/static/js/app.js` | `/api/chat` and `/api/chat/stream` both exist; SSE has meta, chunk, complete, error, and `[DONE]`; client parses event types; chat sessions and export suggestions exist. | SSE buffering is in process memory; cancel route acknowledges only; client falls back on partial response; no explicit idempotency for duplicate sends. | Need Chat V2 service layer, durable session branches, attachment registry, retry/resume semantics, idempotency, stricter error envelope. | Prompt 4 | Blocker |
| Market Sentinel | `kuro_backend/finance_db.py`, `kuro_backend/price_ticker_worker.py`, `kuro_backend/market_sentinel.py`, `main.py`, `kuro_backend/execution/openclaw_bridge.py` | Quantitative price updater; stale-data guard; deduped Telegram alerts; per-user market tables; admin/manual scan route. | Uses `yfinance`, Gemini, OpenClaw, and local SQLite in one flow; route `/api/sentinel/latest` currently has only a docstring body and returns `null`. | Need explicit decision-support disclaimers, source confidence, scan job state, provider isolation, no-guarantee wording, structured Market V2 records. | Prompt 7 | Non-blocker for foundation; blocker for market enterprise |
| Telegram API | `kuro_backend/telegram_notifier.py`, `kuro_backend/telegram_center/*`, `main.py` | Retry sender, DLQ fallback, inbound queue, rate limiting, authorized chat IDs, digesting, pending action confirmation. | Identity maps mostly to admin profile; Telegram bot runs alongside service process; operational action scope is lightweight. | Need Telegram V2 API/service boundary, stronger audit model, per-action RBAC, clearer inbound/outbound contracts, testable worker lifecycle. | Prompt 8 | Non-blocker for foundation |
| Overall API/middleware | `main.py`, `TraceMiddleware`, `validate_token_dependency`, `require_admin_user` | Trace ID header propagation exists; cookie JWT auth exists; admin helper exists; public runtime route hides topology. | Middleware resolves only trace_id; no single request context for tenant, runtime, roles, flags, request_id; repeated auth checks. | Need `/api/v1`, typed envelopes, central exception handling, rate limits, request context, idempotency, public-safe capabilities. | Prompt 0, 9 | Blocker |
| Frontend UI/UX | `web_interface/templates/index.html`, `web_interface/static/js/app.js`, `web_interface/static/css/style.css` | Rich chat UI, sessions drawer, SSE streaming, attachments, search, export, admin-only nav hiding, playground panel. | Large single JS file; CDN dependencies; markdown rendered with `marked` without an obvious sanitizer; admin hiding is not authorization. | Need feature-flagged Frontend V2 entry, smaller modules, safer markdown rendering, runtime/provider controls, provenance/trace UX. | Prompt 10 | Non-blocker for foundation |
| Observability | `kuro_backend/observability.py`, `kuro_backend/telemetry/cognition_trace.py`, `main.py`, `langgraph_core.py` | Phoenix/OpenTelemetry hooks; trace middleware; latency metrics; cognition trace records nodes, tools, memory namespace. | Trace coverage is uneven across all storage/tool/memory writes; Phoenix auth is noted as disabled for local network; no central SLO dashboard contract. | Need GenAI semantic attributes, retrieval/tool/memory spans, request context propagation, redaction policy, eval telemetry. | Prompt 11 | Blocker before enterprise ops |
| Security/RBAC | `main.py`, `kuro_backend/auth_db.py`, `kuro_backend/governance/*`, `kuro_backend/runtime/boundary_guard.py`, `kuro_backend/tools/*` | JWT cookies; bcrypt; admin helper; boundary guard; HITL approval for high-risk tools; uploaded file isolation by username. | Admin is username-based; no OIDC/SAML role mapping; no tenant/workspace authz; CSRF posture not explicit for mutating form endpoints. | Need claim/role mapping, tenant/workspace scope enforcement, CSRF review, audit logs on admin and memory export/delete, prompt injection isolation. | Prompt 0, 9, 11 | Blocker |
| Deployment/secrets | `kuro_backend/config.py`, `.gitignore`, `main.py`, `requirements.txt` | Secrets are env-driven; `JWT_SECRET_KEY` is required; runtime files are gitignored; backups exist. | `.env` exists locally; no container/deployment manifest in reviewed scope; optional provider keys are checked ad hoc; startup imports can fail if required env is missing. | Need `.env.example`, secrets docs, container files, health checks, runbooks, backup restore docs. | Prompt -1, 0, 12 | Blocker |
| Tests | `tests/`, `conftest.py` | Broad test suite covers runtime, memory, chat, ingestion, provider, Telegram, market, export, API/SSE contracts. | No central enterprise baseline tests yet; full suite may be slow; AI behavior testing depends on mocks in many places. | Need phase-specific contract tests for flags, storage, Memory V3, API v1, RBAC matrix, migration parity. | Prompt -1 onward | Non-blocker |
| Documentation | `SYSTEM_MAP.md`, `docs/architecture/*`, `docs/testing/*` | Strong system map and architecture/testing docs exist; prompt pack provides phase plan. | Documentation is version-rich but not yet an enterprise control-plane runbook set. | Need enterprise refactor docs, inventories, final acceptance report, runbooks, data catalog, restore docs. | Prompt -2, -1, 14 | Non-blocker |

## High-Confidence Refactor Priorities

1. Keep default runtime behavior unchanged through feature flags.
2. Create a safety baseline and backups before code refactor.
3. Introduce a storage/data catalog before Memory V3 so migrations are auditable.
4. Build Memory V3 behind flags before altering chat or UI behavior.
5. Treat public API routes and admin routes as separate contracts.
6. Preserve `/api/chat`, `/api/chat/stream`, current Telegram behavior, Market Sentinel behavior, and OpenClaw behavior until each replacement is feature-flagged.

## Notable Existing Strengths

- `kuro_backend/db_utils.py` already uses `PRAGMA table_info()` style column checks through `add_column_if_missing`.
- `main.py` already has `TraceMiddleware` and `api_success` / `api_error` helpers.
- `RuntimeRegistry` and runtime YAML files provide a good control-plane seed.
- `memory_coordinator.safe_mem0_retrieve()` degrades safely on Mem0 failure or timeout.
- `chat_history.py` has per-user and per-chat filters for session history.
- `ingestion_center` separates document metadata in SQLite from Chroma vectors.
- `telegram_notifier.py` has retry and DLQ fallback behavior.
- `openclaw_bridge.py` has disabled-mode safe responses and circuit-breaker state.

## Key Blockers Before Enterprise Readiness

- There is no single governed memory system of record.
- There is no first-class tenant/workspace model across persisted business objects.
- Admin authorization is username-based rather than role/claim-based.
- API contracts are not versioned or centrally typed.
- Storage migrations are distributed across modules.
- Prompt bundles are not centrally versioned or hash-addressed.
- Frontend and backend feature availability are not yet driven by an enterprise flag snapshot.

## Verification Plan For This Phase

Prompt -2 requires no functional code changes. Verification is therefore:

- Confirm the seven audit documentation files exist.
- Run `python -m compileall kuro_backend main.py`.
- Run `pytest tests/ -x --tb=short`.

