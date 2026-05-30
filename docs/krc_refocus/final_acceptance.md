# KRC Refocus Final Acceptance

## Scope

KRC is refocused into Kuro Research Center, a Playground-first Kuro Playground
workspace for research. KS remains separate for daily chat.

## Acceptance Checklist

| Requirement | Status |
|---|---|
| Legacy mode still works | Passed through full regression suite |
| KRC mode is playground-first | Implemented in UI V1 with Kuro Playground landing/nav |
| UI V1 remains production | `index.html` remains the single dashboard shell |
| Frontend V2 shell not reintroduced | No Frontend V2 shell added |
| Daily features hidden/disabled in KRC | Profile flags and scheduler flags added |
| Knowledge API returns approved knowledge only | Implemented in `knowledge_center` |
| Candidate write disabled by default | `KURO_KRC_KNOWLEDGE_CANDIDATES_ENABLED=false` |
| QA Playground hidden/disabled in KRC default | `KURO_KRC_QA_PLAYGROUND_ENABLED=false` |
| QA productization track is feature-flagged | `KURO_KRC_QA_PRODUCTIZATION_ENABLED=false` by default |
| `/api/chat/stream` compatibility preserved | No legacy chat stream replacement |
| Admin auth preserved | KRC admin routes use existing admin dependency |
| KRC and KS DB/history separation documented | SYSTEM_MAP and KRC docs updated |

## Verification

Phase gates run during implementation:

- Phase 0 baseline: `589 passed`
- Phase 1 full gate: `594 passed`
- Phases 2-4 full gate: `597 passed`
- Phases 5-6 full gate: `604 passed`
- Phases 7-8 full gate: `607 passed`
- Phase 9 full gate: `610 passed`
- Phase 10 doc gate: `2 passed`

Final phase 10 verification used:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

Latest verification result: `623 passed, 187 warnings`.

`python` is not available on this host; `python3` is the working interpreter.
