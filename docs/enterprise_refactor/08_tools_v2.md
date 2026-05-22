# Enterprise Refactor Phase 6 Tools V2

Phase 6 adds a governed Tool Runtime V2 for web search, deep research, tasks, reminders, agent mode, approval, and audit. Default runtime behavior is unchanged because all new tool flags remain `false`.

## Flag Behavior

- `KURO_AGENT_TOOLS_V2_ENABLED=false` hides Agent Mode and OpenClaw bridge tools.
- `KURO_WEB_SEARCH_V2_ENABLED=false` hides and blocks Web Search V2.
- `KURO_DEEP_RESEARCH_V2_ENABLED=false` disables Deep Research V2 APIs and tool execution.
- `KURO_TASKS_V2_ENABLED=false` disables Tasks V2 and Reminders V2 APIs and tool execution.
- Routes are mounted additively, but handlers enforce flags before doing work.

## Package

Added package:

```text
kuro_backend/tools_v2/
```

Modules:

- `schemas.py` - tool definitions, execution requests/results, approval, audit, deep research, task, and reminder schemas.
- `registry.py` - default tool catalog and flag-aware visibility.
- `policy.py` - runtime, role, input, approval, and rate-limit policy boundary.
- `executor.py` - structured execution, safe errors, trace IDs, approval checks, audit logging, and FastAPI routes.
- `approvals.py` - SQLite-backed approval request lifecycle.
- `audit.py` - SQLite-backed audit events.
- `web_search.py` - Serper-backed web search adapter with normalized sources.
- `deep_research.py` - Kuro-native research job lifecycle with source scoring and exportable markdown report.
- `tasks.py` - clean `tasks_v2` table and CRUD store.
- `reminders.py` - clean `reminders_v2` table and CRUD store.
- `agent_mode.py` - bounded planning loop using `KURO_AGENT_MAX_STEPS`, default `5`.

## Governance

Every tool definition includes:

- `tool_id`
- `display_name`
- `description`
- `category`
- `risk_level`
- `requires_approval`
- `requires_admin`
- `allowed_runtime_ids`
- `allowed_roles`
- `input_schema`
- `output_schema`
- `timeout_s`
- `budget_cost`
- `enabled_flag`

High and critical risk tools require approval. The OpenClaw bridge additionally requires admin execution and delegates only through the existing `execution.service.execute_openclaw_skill_sync` facade, preserving the existing OpenClaw safety checks and circuit breaker.

## Storage

The default DB is:

```text
<WORKING_DIR or repo root>/kuro_tools_v2.db
```

Override with:

```text
KURO_TOOLS_V2_DB_PATH=/path/to/kuro_tools_v2.db
```

Tables:

- `tool_approval_requests_v2`
- `tool_audit_log_v2`
- `deep_research_jobs_v2`
- `tasks_v2`
- `reminders_v2`

The router creates the executor lazily so importing `main.py` with flags off does not eagerly create the Tools V2 DB.

## APIs

Tool catalog and execution:

```text
GET /api/tools
POST /api/tools/{tool_id}/execute
```

Deep Research V2:

```text
POST /api/deep-research/jobs
GET /api/deep-research/jobs/{job_id}
GET /api/deep-research/jobs
```

Tasks V2:

```text
POST /api/tasks
GET /api/tasks
PATCH /api/tasks/{task_id}
DELETE /api/tasks/{task_id}
```

Reminders V2:

```text
POST /api/reminders
GET /api/reminders
PATCH /api/reminders/{reminder_id}
```

Admin governance:

```text
GET /api/admin/tools/audit
GET /api/admin/tools/approvals
POST /api/admin/tools/approvals/{approval_id}/approve
POST /api/admin/tools/approvals/{approval_id}/deny
```

The old Habits endpoint remains legacy `410`. Reminders are intentionally superseded by the clean V2 endpoints when `KURO_TASKS_V2_ENABLED=true`.

## Verification

Phase 6 adds `tests/test_tools_v2.py` covering:

- tools disabled by default
- safe tool list
- high-risk approval flow
- mocked web search with normalized sources
- mocked deep research job lifecycle
- task create/list/update/delete
- no cross-user task access
- reminder create/list/update
- agent max-step enforcement
- OpenClaw bridge safety not bypassed
- API task and approval flow

Acceptance gate:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

The unqualified `python` command is unavailable in this environment, as recorded in the phase -1 baseline.
