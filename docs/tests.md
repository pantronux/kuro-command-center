# KCC Tests

Run:

```bash
pytest tests/ -x --tb=short
```

`pytest.ini` scopes this physical app to KCC boundary tests:

- Command Center renders for admin
- non-admin access is forbidden
- KRC research routes are absent
- daily chat shell is absent
- KRC Advisor, research-center, and KRC shell artifacts are quarantined under `app_excluded/`
- KCC shows ops modules
- Knowledge ingest ops use HTTP client

Latest verification on 2026-05-31:

- `python3 -m compileall kuro_backend main.py`: passed
- `pytest tests/ -x --tb=short`: `9 passed, 10 warnings`
