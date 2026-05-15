# V2 Phase 2 UAT Result Template

Tanggal:
Executor:
Branch:
Commit:
Mode:
- `KURO_V2_STRICT_MODE=false` / `true`

## Automated Gate

- [ ] `scripts/test_v2_phase2_with_report.sh` pass
- [ ] Report file tersimpan:
- [ ] `python3 -m pytest tests/ -x --tb=short` pass

## Smoke API (Mocked)

- [ ] `python3 scripts/smoke_v2_phase2_api.py` pass

## Scenario Checklist

1. Legacy `/api/chat/stream` tanpa runtime_id:
- [ ] Pass
- Bukti:

2. Runtime dari FormData:
- [ ] Pass
- Bukti:

3. Mismatch query/form runtime -> `400`:
- [ ] Pass
- Bukti:

4. Existing session runtime reuse:
- [ ] Pass
- Bukti:

5. Existing session runtime conflict -> `409`:
- [ ] Pass
- Bukti:

6. Public `/api/runtimes` field safety:
- [ ] Pass
- Bukti:

7. Admin runtime unknown -> `404`:
- [ ] Pass
- Bukti:

8. Boundary violations limit guard:
- [ ] Pass
- Bukti:

9. Audit mode (log only):
- [ ] Pass
- Bukti:

10. Strict mode (safe block, non-500):
- [ ] Pass
- Bukti:

## Observability Snapshot

- `runtime_query_form_mismatch_400_total`:
- `runtime_conflict_409_total`:
- `boundary_violation_total`:
- `boundary_violation_total:<runtime_id>`:

## Findings

### Bug / Regression

### Minor Issue

### Follow-up Action
