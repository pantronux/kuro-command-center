# Enterprise Refactor Phase 11: Observability and Governance

Phase 11 adds an admin-only enterprise observability layer without replacing the
existing Phoenix/OpenTelemetry integration.

## Scope

- Package: `kuro_backend/enterprise_observability/`
- Router:
  - `GET /api/admin/observability/summary`
  - `GET /api/admin/observability/traces`
  - `GET /api/admin/observability/security-events`
  - `GET /api/admin/observability/evals`
  - `GET /api/admin/observability/market`
  - `GET /api/admin/observability/memory`
- Local store: `KURO_ENTERPRISE_OBSERVABILITY_DB_PATH`, defaulting to
  `WORKING_DIR/kuro_enterprise_observability.db`.

## Safety Model

`KURO_ENTERPRISE_OBSERVABILITY_ENABLED` still defaults to `false`. Admin routes
are mounted so operators can inspect the store, but noisy automatic event writes
only run through flag-aware helpers.

Trace and metadata persistence uses a shared redaction policy:

- Secret-like keys such as API keys, tokens, passwords, authorization headers,
  cookies, and credentials are redacted.
- Prompt-like keys are summarized as redacted text lengths unless
  `KURO_OBSERVABILITY_LOG_PROMPTS_ENABLED=true`.
- Known secret environment values are not persisted.
- Traces are exposed only through admin endpoints.

## Recorded Domains

The package can record:

- Chat and provider latency
- Provider errors and fallback decisions
- Token usage
- Memory retrieval/write latency and conflict counts
- Tool calls and denials
- Market source freshness
- Telegram DLQ counts
- SSE disconnects
- Structured output validity
- Evaluation or hallucination scores

Existing Phoenix/OpenTelemetry behavior remains untouched; legacy in-memory
latency and counter snapshots are included in the enterprise summary endpoint.

## Audit Event Contract

Audit events include:

`event_id`, `event_type`, `actor_username`, `actor_role`, `workspace_id`,
`runtime_id`, `chat_id`, `resource_type`, `resource_id`, `action`, `result`,
`trace_id`, `created_at`, and `metadata_json`.

Security events use the same actor/resource/trace shape and support:

- `prompt_injection_detected`
- `memory_poisoning_suspected`
- `tool_denied`
- `excessive_agency_blocked`
- `sensitive_info_blocked`
- `cross_runtime_access_attempt`
- `cross_user_access_attempt`
- `provider_error`
- `schema_validation_failed`

## Smoke Evaluations

The admin eval endpoint supports `run_smoke=true` to run deterministic checks:

- Memory retrieval quality smoke eval
- SSE contract eval
- Market Sentinel source quality eval
- Provider fallback eval
- Boundary leakage eval

These smoke evals are local and deterministic. They do not call external model
providers.

## Verification

Target commands:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/test_enterprise_observability.py -q
pytest tests/ -x --tb=short
```
