# Integration & Data Integrity Hardening Details

Dokumen ini merangkum patch final untuk plan hardening P0-P3 pada integrasi LangGraph, OpenClaw, Memory, API, dan SSE.

## Scope yang Dipatch

File utama:
- `kuro_backend/langgraph_core.py`
- `kuro_backend/execution/openclaw_bridge.py`
- `kuro_backend/chat_history.py`
- `kuro_backend/memory_manager.py`
- `kuro_backend/tools/base_tools.py`
- `main.py`
- `web_interface/static/js/app.js`
- `tests/test_api_sse_contract.py`

## P0 - Security & Approval Integrity

Perubahan:
- Approval token sekarang **nonce-only** (`approve <nonce>`). Token plain `y` tidak lagi diterima.
- Pending approval disimpan **session-scoped** memakai `approval_scope` berbasis `X-Chat-Session` + persona.
- Ditambahkan metadata approval:
  - `nonce`
  - `expires_at` (TTL 10 menit)
  - `payload_hash`
  - `trace_id`
- Saat approval dieksekusi:
  - nonce diverifikasi,
  - `payload_hash` diverifikasi ulang sebelum tool dieksekusi.
- Lifecycle audit log diperluas:
  - `requested`
  - `token mismatch`
  - `cancelled`
  - `executed`
  - `cleared`
  Semua event membawa korelasi `trace_id`.
- Safe fallback pada jalur LangGraph tetap dipertahankan (tidak auto-route ke legacy tool path saat gagal).

## P1 - Persona & Memory Data Integrity

Perubahan:
- Background memory tasks membawa `persona_scope` eksplisit.
- Summarization ke Chroma dipanggil dengan scope persona eksplisit.
- Integritas served/stored response dijaga dengan menyimpan canonical response yang sama.
- Idempotency `chat_history`:
  - kolom `request_id` ditambahkan (migration-safe),
  - unique index parsial `(platform, role, request_id)` saat `request_id` tidak null,
  - write memakai `INSERT OR IGNORE`.
- Platform parity:
  - Telegram message user/assistant kini ditulis ke `chat_history` dengan persona + request id.

## P2 - OpenClaw Execution Reliability

Perubahan:
- Circuit breaker ditingkatkan dengan perilaku **half-open probe** setelah cooldown.
- Claim slot half-open dibuat atomic (`_try_begin_half_open_probe`) untuk mencegah race condition probe ganda.
- Typed execution policy:
  - `execution_mode=readonly|mutating`
  - mutating request wajib punya command/task eksplisit.
- Payload bridge membawa `execution_mode`.
- Router tool dan callable signature disejajarkan agar `execution_mode` konsisten.

## P3 - API/SSE Contract Hardening

Perubahan:
- Frontend stream request memakai `authFetch` + session header `X-Chat-Session`.
- SSE parser frontend diperkuat:
  - CRLF-safe normalization
  - multi-line `data:` merge
  - terminal error event preservation
- API stream/non-stream menambahkan envelope konsisten:
  - `status`
  - `data`
  - `error`
  - `trace_id`
  dan tetap menyertakan field lama penting untuk kompatibilitas frontend.
- Ditambahkan contract tests SSE di:
  - `tests/test_api_sse_contract.py`
  - memverifikasi urutan event `meta -> chunk* -> complete`
  - memverifikasi format event `error`.

## Session Scope Design

- Client menghasilkan `kuro_chat_session_id` di `localStorage`.
- Semua request API via `authFetch` mengirim `X-Chat-Session`.
- Backend memvalidasi pola header (`[A-Za-z0-9._:-]{8,128}`).
- Scope approval dibangun sebagai:
  - `web:<session_id>:<persona>`
  - `telegram:<chat_id>:<persona>`

## Verifikasi yang Disarankan

Jalankan:

```bash
python3 -m py_compile main.py kuro_backend/langgraph_core.py kuro_backend/execution/openclaw_bridge.py kuro_backend/chat_history.py kuro_backend/memory_manager.py kuro_backend/tools/base_tools.py
pytest -q tests/test_api_sse_contract.py
```

Checklist manual:
- Kirim instruksi tool mutating, pastikan respons minta `approve <nonce>`.
- Coba approve dengan nonce salah, pastikan ditolak.
- Coba `cancel`, pastikan pending approval dibatalkan.
- Ulangi request stream dengan reconnect, pastikan `chat_history` tidak duplikat untuk `request_id` yang sama.
- Simulasikan OpenClaw unavailable sampai circuit open, tunggu cooldown, lalu verifikasi half-open probe recovery.
