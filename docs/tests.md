# KCC Tests

Run:

```bash
pytest tests/ -x --tb=short
```

`pytest.ini` scopes this physical app to KCC boundary tests:

- Command Center renders for admin
- non-admin access is forbidden
- KRC research routes are absent
- KCC shows ops modules
- Knowledge ingest ops use HTTP client
