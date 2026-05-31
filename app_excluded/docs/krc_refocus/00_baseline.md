# KRC Refocus Phase 0 Safety Baseline

Phase 0 established a non-destructive baseline before KRC profile work.

## Snapshot

- Working repo: `/home/kuro/projects/kuro`
- Branch: `krc-playground-refocus`
- Backup: `/home/kuro/projects/kuro/backups/krc_refocus_20260527_0930`
- Protected runtime assumptions: HTTPS port 8443, UI V1, legacy
  `/api/chat/stream`, and admin cookie auth.

## Baseline Verification

`python` is not available on this host, so the equivalent `python3` command was
used for compile verification.

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

Baseline result before refocus changes: `589 passed`.
