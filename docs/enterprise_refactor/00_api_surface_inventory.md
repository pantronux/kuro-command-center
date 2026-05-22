# API Surface Inventory

Date: 2026-05-22
Scope: current API/page route inventory for Prompt -2.
Primary source: `main.py`.

## Route Groups

| Group | Routes | Auth posture observed | Notes |
|---|---|---|---|
| Pages | `GET /`, `/chat`, `/login`, `/profile`, `/observability`, `/intelligence`, `/ingestion`, `/ingestion/analytics`, `/ingestion/logs`, `/tutorial`, `/playground/tutorial`, `/compliance`, `/market` | Mixed: login public; app pages use cookie validation; ingestion pages admin-only; market page appears public page shell. | Page rendering is in `main.py` with file/template responses. |
| Auth/user | `POST /api/login`, `GET /api/auth/verify`, `GET /api/auth/stats`, `POST /api/auth/logout`, `GET /api/me`, `POST /api/user/update`, `POST /api/user/change-password`, `POST /api/user/update-persona` | Cookie JWT; some admin/stat restrictions. | JWT helper is local to `main.py`; admin is username equality. |
| Legacy history/chat | `GET /api/history`, `DELETE /api/history`, `GET /api/chat/search`, `POST /api/chat`, `POST /api/chat/stream`, `DELETE /api/chat/stream/{request_id}` | Cookie JWT for chat and history; stream cancel does not enforce request ownership beyond endpoint access. | `/api/chat` and `/api/chat/stream` must remain backward compatible. |
| Runtime/schema | `GET /api/runtimes`, `GET /api/schemas`, `GET /api/schemas/{contract_id}` | Public for runtime/schema list. | `/api/runtimes` intentionally returns public-safe fields only. |
| QA playground | `POST /api/playground/qa/interpret`, `/generate-testcases`, `/generate-gherkin` | Cookie JWT; feature flag check for QA playground. | Full `/api/playground/*` router may mount conditionally through `playground_runtime.api`. |
| Admin runtime | `GET /api/admin/runtimes/{runtime_id}`, `/api/admin/boundary-violations`, `/api/admin/runtime-health` | Cookie JWT plus admin username check. | Full runtime config is admin-only. |
| System/observability | `GET /api/system-status`, `/api/log-storage`, `/api/proxmox-status`, `/api/health`, `/api/observability/status`, `/tokens`, `/latency`, `/cleanup`, `/api/evaluation/summary` | Mixed; several are admin-only by route code. | Needs central admin dependency and versioned contract. |
| Backup | `GET /api/backup/status`, `POST /api/backup/run`, `GET /api/backup/history` | Admin-only via `require_admin_user`. | Good foundation for Prompt -1/-12 restore docs. |
| Memory/compliance old routes | `GET /api/system-analysis`, `POST /api/index-path`, `POST /api/memory/reindex`, `GET /api/memory/stats`, `POST /api/compliance/ingest`, `GET /api/compliance/stats`, `GET /api/compliance/search` | Mixed; memory routes require cookie/admin checks in code sections. | Compliance UI routes later return 410 for purged compliance module. |
| Chat sessions | `GET /api/chats`, `POST /api/chats`, `GET /api/chats/{chat_id}/messages`, `PUT /api/chats/{chat_id}`, `DELETE /api/chats/{chat_id}`, `POST /api/chats/{chat_id}/pin`, `/unpin`, `PUT /messages/{msg_id}/edit`, `POST /messages/{msg_id}/regenerate`, `POST /messages/{msg_id}/bookmark`, `GET /bookmarks`, `GET /search`, `GET /export` | Cookie JWT; functions filter by username for many operations. | Strong UX feature set; needs idempotency and typed service layer. |
| Export | `GET /api/export/history`, `POST /api/export`, `GET /api/export/{job_id}`, `GET /api/export/{job_id}/download` | Cookie JWT; export manager validates ownership. | Universal export engine already present. |
| Intelligence | `GET /api/intelligence/history`, `/latest`, `/run` | Cookie/admin checks vary by route. | Should be normalized under API v1 later. |
| Ingestion | `GET /api/ingestion/datasets`, `/{dataset_uuid}`, `/chunks`, `/lineage`, `/jobs`, `/search`, `/analytics/overview`, `/analytics/retrieval`, `/logs`, `/chroma/health`, `/graph/{dataset_uuid}`, `POST /upload`, `/reindex`, `/orphan-sources/reingest`, `/archive`, `/delete`, `/chroma/cleanup-orphans` | Admin-only through `require_admin_user`. | Good admin boundary; routes expose operational details appropriately for admin. |
| Files | `POST /api/read-file`, `GET /api/list-files` | Cookie JWT; file listing filters by user. | File path safety should remain part of Prompt 9/11 review. |
| Disabled compliance | `GET /api/compliance/progress/{standard}`, `/evidence`, `/search`, `POST /api/compliance/analyze`, `GET /api/compliance/audit-trail` | Return `410 Gone`. | Backward compatibility preserved with safe disabled responses. |
| Dashboard WebSocket | `WS /ws/dashboard` | Cookie JWT in WebSocket. | Sends dashboard refresh/UI command/greeting events. |
| Finance | `GET /api/finances/budget`, `POST /api/finances/budget`, `GET /api/finances/expenses`, `POST /api/finances/expenses`, `DELETE /api/finances/expenses/{expense_id}`, `GET /api/finances/api-usage` | Cookie JWT; username filters. | Uses `finance_db.py` and Pydantic service schemas. |
| Market Sentinel | `GET /api/market/watch`, `POST /api/market/watch`, `DELETE /api/market/watch/{symbol}`, `GET /api/market/hud`, `GET /api/sentinel/latest`, `/stocks`, `/stock/{code}`, `/pins`, `POST /api/sentinel/pins/{code}`, `/run`, `/price-update`, `GET /api/openclaw/skills`, `GET /api/market/brief` | Cookie JWT for most; manual run/price update admin-only; OpenClaw skills admin-only. | `/api/sentinel/latest` currently has no implementation body beyond docstring. |
| Persona admin | `POST /api/persona`, `GET /api/persona`, `GET /api/persona/history/stats`, `/preview`, `POST /reclassify`, `/override`, `/restore` | Cookie JWT; admin posture should be verified per route. | Frontend includes persona history admin controls. |

## Contract Observations

- Response shapes are mixed: some return raw dicts, some use `api_success`, some use `JSONResponse`, and some return direct lists.
- Error shapes are mixed: `HTTPException`, `api_error`, and route-specific `{"status": "error", "message": ...}` all exist.
- Query/form parsing is route-local. `/api/chat` and `/api/chat/stream` accept `runtime_id` via query or form alias.
- Public topology exposure is partially controlled: `/api/runtimes` hides internal config, while `/api/admin/runtimes/{runtime_id}` exposes full config.
- There is no central idempotency or request body hashing for mutating endpoints.

## API Risks To Carry Forward

1. `main.py` owns too many API groups for enterprise change velocity.
2. Auth and admin checks are repeated rather than centralized.
3. API v1 does not exist yet.
4. Public capabilities route does not exist yet.
5. SSE contract is good but should be locked by tests before refactor.
6. In-process SSE replay buffers are not deployment-safe.
7. Some routes expose operational topology; this is acceptable only behind admin checks.
8. Market Sentinel API includes one incomplete route body.
9. Mutating routes do not share idempotency handling.
10. Frontend expects several legacy response shapes, so compatibility tests are required before changing route envelopes.

