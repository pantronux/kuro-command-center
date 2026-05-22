# Enterprise Refactor Phase 10: Frontend V2 Chat UX

## Scope

Phase 10 adds a feature-flagged Frontend V2 chat workspace. The legacy
`index.html` dashboard remains the default when `KURO_FRONTEND_V2_ENABLED=false`.

When the flag is true, `/` and `/chat` render `index_v2.html`.

## Files

- `web_interface/templates/index_v2.html`
- `web_interface/static/css/v2.css`
- `web_interface/static/js/v2/api.js`
- `web_interface/static/js/v2/chat.js`
- `web_interface/static/js/v2/sidebar.js`
- `web_interface/static/js/v2/profile_menu.js`
- `web_interface/static/js/v2/admin_settings.js`
- `web_interface/static/js/v2/streaming.js`
- `web_interface/static/js/v2/model_settings.js`
- `web_interface/static/js/v2/tasks.js`
- `web_interface/static/js/v2/market.js`

No React/Vue/build step was introduced. The V2 client is Vanilla JS modules
served from the existing static mount.

## UX Layout

Frontend V2 uses:

- left sidebar focused on chat sessions
- pinned and recent session lists
- new chat and chat search
- compact top bar with model selector and context drawers
- top-right profile menu
- admin settings inside the profile menu
- conversational message stream
- composer tool row for web search, deep research, agent mode, task, reminder,
  and market actions

The profile menu renders `Administration Settings` only when the backend context
marks the user as admin. Backend admin dependencies remain unchanged and still
enforce direct API access.

## Admin Settings

The admin modal contains tabs for:

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

Each tab calls an existing authenticated/admin endpoint and shows an unavailable
state if the endpoint is disabled or not present.

## Chat And Tools

The V2 client uses existing APIs:

- `/api/chats`
- `/api/chats/{chat_id}/messages`
- `/api/chats/{chat_id}/settings`
- `/api/chat/v2/stream`, with fallback to `/api/chat/stream`
- `/api/models`
- `/api/tasks`
- `/api/reminders`
- `/api/market-v2/analyze`

Unavailable feature paths surface a disabled/unavailable state in the status bar.
No raw API keys or token values are embedded in the HTML.

## Streaming

`streaming.js` parses SSE events and supports:

- token/chunk
- tool events
- memory context
- error
- done/complete

It uses bounded retry/backoff before a stream starts and does not buffer the full
assistant response before displaying tokens.

## Verification

Focused tests:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/test_frontend_v2.py -q
```

Full acceptance check:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```
