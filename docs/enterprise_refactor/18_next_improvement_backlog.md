# Enterprise Refactor Phase 14: Next Improvement Backlog

This backlog starts after the Phase 14 acceptance report. Priorities are
ordered by rollout risk and enterprise value.

## P0: Pilot-Critical

### Memory V3 Production Rollout

- Add staged rollout plan from shadow-write to read-enabled to primary-read.
- Add operator dashboard for conflicts, redactions, access logs, and retention.
- Add migration/reconciliation checks between legacy memory and Memory V3.
- Acceptance: Memory V3 can be enabled for one pilot workspace with rollback
  to legacy memory and no cross-user context bleed.

### Chat V2 Rollout

- Run browser smoke tests for `index.html` on desktop and mobile widths after
  each dashboard redesign.
- Add Chat V2 SSE replay/timeout tests around provider fallback and disconnect.
- Add operator toggle guidance for `KURO_CHAT_V2_ENABLED`.
- Acceptance: one pilot user can use Chat V2 for daily work while legacy chat
  remains available.

### Provider Registry Integration

- Validate Gemini, OpenAI, Anthropic, and DeepSeek adapters with live keys in
  staging.
- Add provider-specific rate-limit/backoff policy.
- Add model-cost and usage reporting per alias.
- Acceptance: provider fallback works in staging without leaking keys or raw
  provider errors to public responses.

### Market Sentinel V2 Pilot

- Enable V2 watchlist and analysis for a bounded pilot list.
- Compare V2 reports against legacy Sentinel output for precision and recall.
- Add freshness and alert-quality review notes to operator docs.
- Acceptance: V2 produces useful alerts without duplicate or stale spam.

### Dashboard Admin Settings

- Complete feature toggles/status views for enterprise flags, provider health,
  observability, Telegram V2, and Market V2.
- Add route-level admin checks and frontend disabled states.
- Acceptance: an admin can inspect rollout state without editing `.env` for
  every diagnostic check.

### Security/RBAC Hardening

- Replace admin-username checks with role and permission primitives.
- Add route permission matrix and tests for admin/operator/user roles.
- Add audit events for denied admin actions and high-risk tool requests.
- Acceptance: protected endpoints enforce explicit permissions and produce
  audit trails.

## P1: Enterprise Foundation

### PostgreSQL/pgvector Migration Option

- Define repository interfaces for Memory V3, Tools V2, Market V2, Telegram
  V2, and observability stores.
- Add PostgreSQL schema/migration path and pgvector option for memory search.
- Acceptance: pilot can choose SQLite or PostgreSQL without changing route
  contracts.

### Workspace/Tenant Isolation

- Introduce tenant/workspace ownership model across chat, memory, tools,
  market, Telegram, and observability.
- Add isolation tests that prove tenant A cannot query tenant B artifacts.
- Acceptance: every enterprise route carries tenant/workspace authorization.

### SSO/OIDC

- Add OIDC configuration and login callback.
- Map identity claims to users, roles, and tenant memberships.
- Acceptance: staging supports password login and OIDC login side by side.

### OpenTelemetry Collector

- Export traces/metrics/log signals to a configurable collector.
- Keep Phoenix/local observability as dev mode.
- Acceptance: staging emits spans/metrics to an external collector without
  exposing prompt content by default.

### Deep Research V2 Improvements

- Add source ledger, citation quality scoring, resumable jobs, and result
  exports.
- Add budget/limit controls per workspace.
- Acceptance: research jobs are auditable, resumable, and bounded.

## P2: Enterprise Productization

### Enterprise Onboarding

- Add setup checklist for flags, provider keys, backups, Telegram, market
  sources, and observability.
- Acceptance: a new pilot environment can be configured from docs without
  reading source code.

### Compliance Packs

- Add deployment evidence templates for security, backup, audit, and data
  retention controls.
- Acceptance: operators can generate a basic pilot compliance packet.

### Customer-Facing Documentation

- Add user/admin guides for Chat V2, tasks/reminders, model settings, market
  sentinel, Telegram V2, and observability.
- Acceptance: documentation separates end-user, admin, and operator workflows.

### Advanced Model Evaluation

- Add regression datasets, model comparison dashboards, prompt-risk checks,
  and drift alerts.
- Acceptance: model/provider changes can be compared before rollout.
