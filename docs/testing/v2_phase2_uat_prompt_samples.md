# V2 Phase -1..2 UAT Prompt Samples (Manual)

Dokumen ini untuk UAT manual setelah automated test fase `-1..2` hijau.
Fokus: runtime registry, boundary guard, dan backward compatibility.

## Pre-check

1. Pastikan env minimal:
   - `KURO_V2_STRICT_MODE=false` (audit mode, non-blocking)
2. Login sebagai admin (`Pantronux`) dan non-admin (`Faikhira`) untuk cek RBAC.
3. Gunakan endpoint stream lama `/api/chat/stream` tanpa `runtime_id` untuk legacy smoke.

## A. Runtime Fallback & Resolution

1. **Legacy tanpa runtime_id**
   - Prompt: `Buat ringkasan status migrasi V2 hari ini.`
   - Ekspektasi:
     - request sukses (SSE complete),
     - tidak error karena `runtime_id` kosong,
     - fallback ke `sovereign`.

2. **Runtime explicit qa**
   - Request gunakan query `?runtime_id=qa`
   - Prompt: `Tolong jawab sebagai mode QA: list acceptance criteria Prompt 1.`
   - Ekspektasi:
     - request sukses,
     - response konsisten dengan context QA,
     - tidak ada crash state graph.

3. **Runtime tidak dikenal**
   - Request gunakan query `?runtime_id=runtime_aneh_123`
   - Prompt: `Tes fallback runtime.`
   - Ekspektasi:
     - request tetap sukses,
     - fallback aman ke `sovereign`.

## B. Public/Admin Runtime Routes

1. **Public runtime list**
   - `GET /api/runtimes`
   - Ekspektasi:
     - field aman saja (`runtime_id`, `display_name`, `version`, dst),
     - field internal sensitif tidak bocor (`tools`, `prompt_stack`, `memory_namespace`).

2. **Admin runtime detail**
   - `GET /api/admin/runtimes/qa`
   - Ekspektasi:
     - admin bisa lihat full config.

3. **Admin guard**
   - login non-admin, akses endpoint admin di atas
   - Ekspektasi:
     - `403 Forbidden`.

## C. Boundary Guard (Audit Mode)

Mode: `KURO_V2_STRICT_MODE=false`

1. Prompt: `Jalankan market_analysis sekarang.` pada runtime `qa`.
2. Ekspektasi:
   - chat tetap jalan (tidak hard-block),
   - bila ada violation, tercatat di `boundary_violations`,
   - bisa dilihat via `GET /api/admin/boundary-violations`.

## D. Boundary Guard (Strict Mode)

Mode: `KURO_V2_STRICT_MODE=true` lalu restart service.

1. Prompt: `Jalankan market_analysis sekarang.` pada runtime `qa`.
2. Ekspektasi:
   - gagal aman (safe failure), bukan `500` crash,
   - stream kirim event error terkontrol,
   - violation tercatat dengan `trace_id` bila tersedia.

## E. Legacy Chat Smoke (Must-Pass)

1. Kirim 3-5 chat normal tanpa `runtime_id`:
   - `Halo, bantu buat to-do list riset minggu ini.`
   - `Ringkas hasil chat sebelumnya jadi 5 poin.`
   - `Apa prioritas debugging hari ini?`
2. Ekspektasi:
   - semua request sukses,
   - tidak ada regression di alur lama.

## Catatan Eksekusi

- Automated runner: `scripts/test_v2_phase2_ready.sh`
- Opsional full regression:
  - `RUN_FULL_SUITE=1 scripts/test_v2_phase2_ready.sh`
