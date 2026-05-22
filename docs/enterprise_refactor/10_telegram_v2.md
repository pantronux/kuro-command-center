# Enterprise Refactor Phase 8: Telegram API V2

## Scope

Phase 8 adds an additive Telegram API V2 bridge under `kuro_backend/telegram_v2/`.
It does not replace the legacy bot/bootstrap path or `kuro_backend.telegram_notifier`.
The new webhook path is disabled by default through `KURO_TELEGRAM_V2_ENABLED=false`.

## Runtime Surfaces

- `POST /api/telegram/webhook`
- `GET /api/admin/telegram-v2/health`
- `GET /api/admin/telegram-v2/dlq`
- `POST /api/admin/telegram-v2/dlq/{message_id}/retry`
- `GET /api/admin/telegram-v2/mappings`
- `POST /api/admin/telegram-v2/mappings`

The webhook route is public but requires a configured secret. Admin routes use
the same admin dependency as the existing FastAPI application.

## Security

- The webhook rejects requests while `KURO_TELEGRAM_V2_ENABLED` is false.
- The webhook requires `TELEGRAM_WEBHOOK_SECRET`.
- Accepted secret carriers:
  - `X-Telegram-Bot-Api-Secret-Token`
  - `X-Kuro-Telegram-Secret`
  - `X-Telegram-Webhook-Secret`
  - `Authorization: Bearer <secret>`
- Health output exposes only booleans such as `token_configured`; token values
  are never returned.
- Sender mappings are admin-controlled and unknown Telegram senders are rejected
  by default.
- A mapping can pin `telegram_chat_id`; if present, the same sender id from a
  different chat is rejected.

## Storage

`TelegramV2QueueStore` uses SQLite at `KURO_TELEGRAM_V2_DB_PATH`, or
`WORKING_DIR/kuro_telegram_v2.db` by default.

Tables:

- `telegram_v2_outbound_queue`
  - `message_id`
  - `username`
  - `chat_id`
  - `channel`
  - `payload_json`
  - `status`
  - `attempt_count`
  - `next_retry_at`
  - `last_error`
  - `created_at`
  - `sent_at`
- `telegram_v2_sender_mappings`
  - `mapping_id`
  - `telegram_user_id`
  - `username`
  - `telegram_chat_id`
  - `display_name`
  - `active`
  - `created_at`
  - `updated_at`

## Commands

Supported inbound commands:

- `/start`
- `/help`
- `/status`
- `/chat <message>`
- `/research <topic>`
- `/market <symbol>`
- `/task <title>`
- `/remind <time> <text>`

Free-form text is routed as `/chat`. The default `/chat` handler calls
`process_chat_with_graph` with the same runtime boundary as web chat:
`runtime_id="sovereign"`, `runtime_namespace="kuro.sovereign"`, and a
Telegram-scoped approval/session id. This keeps Memory V3 and tool policy
boundaries in the core runtime instead of bypassing them in Telegram code.

Market, research, task, and reminder handlers call the V2 services only when
their feature flags are enabled. Tests inject mocks so no real Telegram or
external provider calls are made.

## Retry And DLQ

Outbound responses are persisted before delivery. `TelegramV2Notifier` marks a
message `retry` on failed sends and schedules `next_retry_at`. Once
`max_attempts` is reached the message moves to `dead`.

Admins can inspect `dead` messages and manually retry them through the DLQ
endpoint. Retrying resets the row to `pending` and runs the configured sender.

## Verification

Focused tests:

```bash
python3 -m compileall kuro_backend/telegram_v2 main.py
pytest tests/test_telegram_v2.py -q
```

Full acceptance check:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```
