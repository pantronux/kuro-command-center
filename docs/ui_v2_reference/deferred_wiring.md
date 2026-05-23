# Deferred Wiring

The static reference intentionally does not call production APIs. These features
need explicit backend contracts before any production wiring.

## Deferred Features

| Feature | Backend dependency | Required tests before enabling |
| --- | --- | --- |
| Deep Research drawer | Job creation, source selection, depth, status polling | Drawer state, job creation errors, cancellation, auth |
| Web Search toggle | Tool runtime capability flag and safe search policy | Toggle gating, citation rendering, disabled state |
| Agent Mode | Governed loop contract and stop controls | Loop start/stop, budget limits, audit trail |
| Task creation | Task endpoint and current-message context handoff | Manual and selected-message task creation |
| Reminder creation | Reminder V2 endpoint and scheduler status | Time parsing, validation, timezone handling |
| Market drawer | Market V2 analysis route, freshness, source quality | No trading claims, stale data warnings |
| Memory V3 admin | Admin-only health and conflict endpoints | Non-admin forbidden, admin tab rendering |
| Provider admin settings | Provider registry and model alias endpoints | No raw secrets, safe aliases only |
| Telegram admin | Admin-only Telegram status/config endpoints | No token exposure |
| Feature flags | Admin-only flag snapshot/update policy | Non-admin forbidden, audit trail |

## Rollback Plan

1. Keep V1 as the production route.
2. Keep all reference files outside active templates and JS bundles.
3. Gate future production changes behind focused tests.
4. Revert only the latest UI slice if a regression appears.
5. Never enable a full V2 route until chat, upload, admin, and playground
   regression tests pass together.

## Endpoint Notes

Known production endpoints that may be relevant later:

- `/api/chat/stream`
- `/api/chats`
- `/api/chats/{chat_id}/messages`
- `/api/chats/{chat_id}/export`
- `/api/playground/*`
- `/api/market/hud`
- `/api/sentinel/*`
- `/api/admin/*`

Unknown or incomplete endpoint contracts must remain reference-only.

