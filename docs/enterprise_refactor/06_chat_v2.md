# Enterprise Refactor Phase 4 Chat V2

Phase 4 adds an enterprise Chat V2 layer for streaming, history, lineage, attachments, session settings, and replay behavior. The default runtime behavior is unchanged because `KURO_CHAT_V2_ENABLED` remains `false`.

## Flag Behavior

- `KURO_CHAT_V2_ENABLED=false` keeps existing `/api/chat` and `/api/chat/stream` behavior unchanged.
- Chat V2 routes are mounted additively, but handlers return disabled status unless the flag is enabled.
- The legacy SSE contract still emits `meta`, `chunk`, `complete`, `error`, and `[DONE]`.
- Chat V2 streaming uses typed SSE envelopes and does not replace legacy streaming in this phase.

## Package

Added package:

```text
kuro_backend/chat_v2/
```

Modules:

- `schemas.py` - settings, request/result, pagination, and streaming envelope models.
- `service.py` - additive FastAPI router and service boundary.
- `streaming.py` - SSE envelope serialization, monotonic event IDs, replay buffer, error/done termination.
- `history.py` - owned session reads, pagination, edit lineage, regeneration lineage, soft delete support.
- `session_settings.py` - persisted session settings repository.
- `attachments.py` - artifact reference sanitization with raw path removal.
- `telemetry.py` - lightweight event/timing logs.

## Idempotent Migrations

`kuro_backend/chat_history.py` now idempotently adds:

Chat sessions:

- `model_alias`
- `provider_alias`
- `temperature`
- `runtime_id`
- `workspace_id`
- `archived_at`
- `deleted_at`
- `mode`
- `tools_enabled`
- `web_search_enabled`
- `memory_v3_enabled`

Chat history:

- `trace_id`
- `event_seq`
- `parent_message_id`
- `branch_id`
- `artifact_refs_json`
- `grounding_refs_json`

Indexes were added for stream sequence, branch lookup, and workspace/user session lookup. The migration does not delete existing history.

## Settings

`ChatSessionSettings` persists:

- `provider_alias`
- `model_alias`
- `temperature`
- `runtime_id`
- `mode`: `default`, `research`, `agent`, `market`, `qa`
- `tools_enabled`
- `web_search_enabled`
- `memory_v3_enabled`

## APIs

Existing APIs remain:

```text
GET /api/chats
POST /api/chats
GET /api/chats/{chat_id}/messages?before_id=&limit=
DELETE /api/chats/{chat_id}
POST /api/chats/{chat_id}/messages/{message_id}/regenerate
```

Chat V2 adds:

```text
GET /api/chats/{chat_id}
PATCH /api/chats/{chat_id}
POST /api/chats/{chat_id}/messages/{message_id}/edit
POST /api/chats/{chat_id}/settings
POST /api/chat/v2/stream
```

The V2 endpoints enforce owner checks before returning session details or mutating session state.

## Streaming

Chat V2 SSE event names:

- `trace`
- `token`
- `tool_call_start`
- `tool_call_delta`
- `tool_call_end`
- `memory_context`
- `structured_output`
- `error`
- `done`

Current implementation emits `trace`, `token`, optional `structured_output`, `error`, and `done`; the remaining envelope names are reserved in the schema for upcoming tool and memory integration.

Replay behavior:

- Event IDs are monotonic per chat stream.
- A small in-memory replay buffer is retained per chat.
- `Last-Event-ID` replays buffered envelopes after that ID.
- If a replayed `done` envelope is present, the handler stops without re-running the model stream.

Termination behavior:

- Successful streams emit `done`.
- Exceptions emit `error` followed by `done`.
- Client disconnects stop the generator without forcing more output.

## Attachments

Existing upload behavior is preserved. Chat V2 stores attachment continuity in `artifact_refs_json`, and response serialization strips raw server paths such as upload directories and archive paths.

## Verification

Phase 4 adds `tests/test_chat_v2.py` covering:

- legacy stream still works when flag false
- Chat V2 stream emits `done`
- error path emits `error` and `done`
- `Last-Event-ID` replay
- settings persistence
- pagination
- edit lineage
- regeneration parent linkage
- attachment reference sanitization
- cross-user access denial

Acceptance gate:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

The unqualified `python` command is unavailable in this environment, as recorded in the phase -1 baseline.
