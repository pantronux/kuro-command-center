# Frontend Inventory

Date: 2026-05-22
Scope: Prompt -2 frontend inventory for current main dashboard.
Primary files: `web_interface/templates/index.html`, `web_interface/static/js/app.js`, `web_interface/static/css/style.css`.

## Current Frontend Shape

| Area | Current files | Behavior |
|---|---|---|
| Main dashboard template | `web_interface/templates/index.html` | Jinja page with Tailwind CDN, Lucide, Font Awesome, Marked.js, Highlight.js, custom CSS, chat shell, sidebar, modals, playground panel, system status, export modal, file preview modal. |
| Main app logic | `web_interface/static/js/app.js` | Chat sending, SSE parsing, sessions, drafts, sidebar, admin nav guards, uploads, drag/drop, file preview, search, export, WebSocket dashboard updates, market HUD polling, playground calls. |
| Styling | `web_interface/static/css/style.css` plus inline style in `index.html` | Glassmorphism UI, themes, chat bubbles, modals, ticker, markdown/code/table handling. |
| Other templates | `web_interface/templates/ingestion_center.html`, `ingestion_analytics.html`, `ingestion_logs.html`, `market.html`, `intelligence.html`, `login.html`, `profile.html`, tutorial templates | Secondary feature surfaces. |

## Main UI Features

- Persona picker with restricted-persona Jinja gating.
- Chat drawer with sessions, pin, rename, export, delete.
- `/api/chat/stream` SSE streaming parser with `meta`, `chunk`, `complete`, `error`, and `[DONE]` handling.
- Stop generation through `AbortController`.
- Drag/drop, paste, and file picker uploads.
- Local draft preservation per chat session.
- Infinite scroll for message history.
- Message toolbar for copy, edit, regenerate, bookmark.
- Markdown rendering, code highlighting, code/table copy actions.
- Export suggestions from assistant response metadata.
- System Status modal.
- Admin-only navigation hiding for ingestion/system status links.
- WebSocket dashboard updates through `/ws/dashboard`.
- Market HUD polling through `/api/market/hud`.
- Playground mode panel with provider/session/execution/artifact actions.

## Strengths

- The frontend already supports a ChatGPT-like interaction loop with streaming, file uploads, sessions, and message actions.
- SSE parsing is event-type aware and avoids double-bubble creation on `complete`.
- Admin-only links are hidden for non-admin users, while backend routes still enforce server checks.
- The UI has a clear left navigation model and a session drawer.
- Export workflows are already visible in the chat UX.

## Risks And Gaps

| ID | Gap | Evidence path | Risk | Proposed phase |
|---|---|---|---|---|
| F-001 | Main JS file is very large and owns many unrelated workflows. | `web_interface/static/js/app.js` | Frontend V2 changes can regress unrelated features. | Prompt 10 |
| F-002 | CDN dependencies are runtime-critical. | `index.html` Tailwind/Lucide/FontAwesome/Marked/Highlight CDNs | Offline/enterprise deployments may fail or violate supply-chain policy. | Prompt 10, 12 |
| F-003 | Markdown rendering uses `marked.parse`; no obvious DOMPurify or equivalent sanitizer in the template. | `index.html`, `app.js` | Stored/model-generated HTML can become XSS risk if unsafe markdown is allowed. | Prompt 10, 11 |
| F-004 | Admin visibility guards are UX-only. | `app.js` `applyAdminVisibilityGuards()` | Must not be treated as security; server enforcement remains required. | Prompt 10 |
| F-005 | Feature availability is not driven by an enterprise capabilities endpoint. | `app.js`, `main.py` | UI cannot safely adapt to feature flags yet. | Prompt 0, 10 |
| F-006 | Runtime/provider selection UX is split between normal/playground mode rather than a consistent control plane. | `index.html`, `app.js` | Users/operators may not understand active runtime/provider/model. | Prompt 5, 10 |
| F-007 | SSE client stores stream metadata only in local variables. | `app.js` `sendMessage()` | Trace/provider/memory provenance is not surfaced in a durable user-visible way. | Prompt 4, 10 |
| F-008 | Stop generation aborts fetch but does not guarantee backend cancellation. | `app.js`, `main.py` cancel route | User expects cancellation but server work may continue. | Prompt 4 |
| F-009 | Upload validation exists client-side but must be treated as advisory. | `app.js` `CONFIG.ALLOWED_TYPES`, `CONFIG.ALLOWED_EXTENSIONS` | Backend file security remains the source of truth. | Prompt 9, 10 |
| F-010 | UI text and version labels are manually embedded. | `index.html` | Enterprise branding/version display can drift from backend version source. | Prompt 10, 14 |
| F-011 | Playground mode is embedded inside main chat app. | `index.html`, `app.js` | Operational/test tooling can complicate main UX and permissions. | Prompt 10 |
| F-012 | Market HUD polling is timer-based. | `app.js` | Could duplicate server load across clients without shared backoff/capability state. | Prompt 7, 10 |

## Route Dependencies From Frontend

High-use backend dependencies observed in `app.js`:

- `/api/me`
- `/api/chats`
- `/api/chats/{chat_id}/messages`
- `/api/chats/{chat_id}`
- `/api/chats/{chat_id}/pin`
- `/api/chats/{chat_id}/unpin`
- `/api/chats/{chat_id}/messages/{message_id}/edit`
- `/api/chats/{chat_id}/messages/{message_id}/regenerate`
- `/api/chats/{chat_id}/messages/{message_id}/bookmark`
- `/api/chat/stream`
- `/api/chat/search`
- `/api/market/hud`
- `/api/system-status`
- `/api/export`
- `/api/export/{job_id}`
- `/api/export/{job_id}/download`
- `/api/list-files`
- `/api/persona`
- `/api/persona/history/*`
- `/api/playground/*`
- `/ws/dashboard`

## Frontend Acceptance Themes For Later Phases

- Frontend V2 must be behind `KURO_FRONTEND_V2_ENABLED=false` by default.
- Existing `index.html` and `app.js` behavior must remain default until cutover.
- A public-safe `/api/capabilities` response should drive visible feature toggles.
- Markdown rendering should be sanitized before any broad enterprise rollout.
- Admin-only UI must remain backed by server-side authorization.
- Streaming UI must preserve current SSE event contract.

