# V2 Phase 2 Test Case (Normalized)

Dokumen ini versi normalize dari `Test Case V2.md`:
- fokus ke **input + expected assertion**
- contoh jawaban LLM dipisahkan dari pass/fail criteria
- dipakai untuk evaluasi objektif

## Day 1 - Legacy Stability

### TC-D1-01 Legacy chat stream
- Input:
  - endpoint `/api/chat/stream` tanpa `runtime_id`
  - prompt: `Halo Kuro, test legacy mode.`
- Expected:
  - HTTP `200`
  - stream selesai (`event: complete`)
  - tidak ada 500

### TC-D1-02 Persona behavior
- Input:
  - persona advisor/chill, prompt normal
- Expected:
  - persona tetap konsisten
  - tidak bocor runtime internals
  - tidak ada boundary error aneh

### TC-D1-03 Memory recall sovereign
- Input:
  - prompt recall konteks sebelumnya
- Expected:
  - retrieval jalan normal
  - tidak ada error namespace

## Day 2 - Runtime + Audit Mode

### TC-D2-01 Public runtimes route safety
- Input:
  - `GET /api/runtimes`
- Expected:
  - field aman saja
  - field internal tidak muncul

### TC-D2-02 Admin runtime route
- Input:
  - `GET /api/admin/runtimes/qa` (admin)
  - `GET /api/admin/runtimes/unknown` (admin)
- Expected:
  - existing -> `200`
  - unknown -> `404`

### TC-D2-03 Runtime explicit qa
- Input:
  - `/api/chat/stream?runtime_id=qa`
  - prompt QA sederhana
- Expected:
  - request sukses
  - tidak crash

### TC-D2-04 Runtime query/form mismatch
- Input:
  - query `runtime_id=qa`, form `runtime_id=sovereign`
- Expected:
  - `400`

### TC-D2-05 Existing session runtime conflict
- Input:
  - session stored `qa`
  - request follow-up pakai `runtime_id=sovereign`
- Expected:
  - `409`

### TC-D2-06 Audit mode boundary
- Precondition:
  - `KURO_V2_STRICT_MODE=false`
- Input:
  - trigger access/tool forbidden
- Expected:
  - tidak hard block
  - violation tercatat

## Day 3 - Strict Mode

### TC-D3-01 Strict mode block
- Precondition:
  - `KURO_V2_STRICT_MODE=true`
- Input:
  - trigger access/tool forbidden
- Expected:
  - block aman (bukan 500)
  - stream error terkontrol

### TC-D3-02 Boundary limit guard
- Input:
  - `GET /api/admin/boundary-violations?limit=-1`
  - `GET /api/admin/boundary-violations?limit=99999`
- Expected:
  - invalid query ditolak validator
  - DB clamp defensif tetap aktif

## Execution Shortcuts

- Automated:
  - `scripts/test_v2_phase2_with_report.sh`
- API smoke:
  - `python3 scripts/smoke_v2_phase2_api.py`
- UAT result form:
  - `docs/testing/v2_phase2_uat_result_template.md`
