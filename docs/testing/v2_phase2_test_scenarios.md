# V2 Phase 2 Test Scenarios (Ready-to-Run)

Scope dokumen ini: validasi hasil Prompt `-1..2` (runtime registry + boundary guard + compatibility V1), **tanpa** masuk Phase 3.

## 1) Fast Automated Gate

Jalankan ini dulu:

```bash
scripts/test_v2_phase2_with_report.sh
```

Opsional full regression:

```bash
RUN_FULL_SUITE=1 scripts/test_v2_phase2_with_report.sh
```

Pass criteria:
- `compileall` sukses
- test runtime/boundary/legacy smoke sukses
- tidak ada failed test

## 2) API Scenario Matrix (Phase 2)

### S1. Legacy stream tanpa runtime_id (must pass)
- Request: `POST /api/chat/stream` tanpa `runtime_id`
- Payload sample:
  - `message=Halo Kuro, test legacy stream`
  - `persona=consultant`
- Expected:
  - HTTP `200`
  - SSE ada `event: complete`
  - tidak ada error boundary

### S2. Runtime dari FormData
- Request: `POST /api/chat/stream` dengan body `runtime_id=qa` (form field)
- Expected:
  - HTTP `200`
  - runtime resolve ke `qa`
  - tidak fallback ke sovereign

### S3. Query/Form runtime mismatch
- Request: `POST /api/chat/stream?runtime_id=qa` + body `runtime_id=sovereign`
- Expected:
  - HTTP `400`
  - pesan jelas mismatch query vs form

### S4. Existing session runtime reuse
- Precondition:
  - session existing punya `chat_sessions.runtime_id='qa'`
- Request:
  - follow-up chat tanpa `runtime_id`
- Expected:
  - runtime otomatis tetap `qa`
  - tidak fallback ke sovereign

### S5. Existing session runtime conflict
- Precondition:
  - session existing punya runtime `qa`
- Request:
  - follow-up chat pakai `runtime_id=sovereign`
- Expected:
  - HTTP `409 Conflict`
  - detail menjelaskan runtime stored vs requested

### S6. Public runtimes route safety
- Request: `GET /api/runtimes`
- Expected:
  - field aman: `runtime_id`, `display_name`, `version`
  - field sensitif tidak bocor: `tools`, `prompt_stack`, `memory_namespace`, provider internals

### S7. Admin runtime exact lookup
- Request:
  - `GET /api/admin/runtimes/qa` (admin)
  - `GET /api/admin/runtimes/not_exists` (admin)
- Expected:
  - existing runtime => `200`
  - unknown runtime => `404` (bukan fallback)

### S8. Boundary violations route limit guard
- Request:
  - `GET /api/admin/boundary-violations?limit=-1`
  - `GET /api/admin/boundary-violations?limit=99999`
- Expected:
  - keduanya ditolak request validator (`422`)
  - DB layer tetap clamp defensif `1..500`

### S9. Boundary guard audit mode
- Env: `KURO_V2_STRICT_MODE=false`
- Request:
  - runtime `qa`, trigger tool yang tidak di-allow
- Expected:
  - tidak diblok hard
  - violation tercatat di `boundary_violations`

### S10. Boundary guard strict mode safe-failure
- Env: `KURO_V2_STRICT_MODE=true`
- Request:
  - runtime `qa`, trigger tool forbidden
- Expected:
  - stream error aman (bukan 500 crash)
  - violation tercatat + trace_id jika ada

### S11. Sovereign legitimate tools not blocked
- Env: strict mode `true`
- Expected:
  - tool sovereign valid tetap allowed
  - tidak false-positive block

### S12. Runtime registry fail-fast sovereign
- Precondition:
  - config sovereign hilang/invalid (test isolated/temp)
- Expected:
  - `RuntimeRegistry.load_all()` raise `RuntimeError`

### S13. Runtime schema compatibility
- Precondition:
  - runtime config `version=2`, `schema_version=1`
- Expected:
  - config tetap bisa load
  - gate cek `schema_version`, bukan `version`

### S14. Mem0 dedup cross-runtime isolation
- Precondition:
  - queued mem0 tasks dengan content mirip di runtime berbeda
- Expected:
  - task runtime A tidak menghapus task runtime B
  - dedup key runtime-scoped

## 3) Prompt Samples (Manual UAT)

Gunakan sample ini setelah S1-S14 untuk sanity check UX:

1. Legacy normal:
   - `Bantu ringkas prioritas kerja hari ini jadi 5 poin.`
2. QA runtime:
   - `Buat 3 test case login valid (format ringkas).`
3. QA runtime strict boundary:
   - `Jalankan market analysis sekarang.`
4. Sovereign explicit:
   - `Ini test runtime sovereign, jawab singkat apakah request normal bisa diproses.`

## 4) Evidence Checklist

Simpan artefak berikut:
- report runner `backups/pre-v2/v2_phase2_test_report_*.txt`
- potongan response untuk S3 (`400`) dan S5 (`409`)
- potongan response untuk S7 unknown runtime (`404`)
- potongan response boundary route invalid limit (`422`)
- 1 contoh row `boundary_violations` (audit/strict)

## 5) Improvement Priority (Recommended)

1. Tambah 1 script smoke API berbasis `TestClient` khusus UAT harian.
2. Tambah endpoint/flag debug ringan untuk menampilkan resolved runtime per request (hanya admin/dev mode).
3. Tambah metrik counter:
   - runtime_conflict_409_total
   - runtime_query_form_mismatch_400_total
   - boundary_violation_total by runtime_id
4. Tambah test performa kecil untuk mem0 queue ketika banyak runtime aktif bersamaan.
5. Rapikan `Test Case V2.md`: pisahkan “contoh jawaban LLM” dari “expected assertion” supaya tidak bias.
