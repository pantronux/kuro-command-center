# Staging

Use staging for release smoke tests before enabling a feature in a pilot.

## Profile

```bash
KURO_DEPLOYMENT_PROFILE=staging
KURO_API_V2_ENABLED=true
KURO_FRONTEND_V2_ENABLED=true
KURO_ENTERPRISE_OBSERVABILITY_ENABLED=true
```

Use non-production Telegram chats and non-production provider keys where
available.

## Release Checks

Run:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

Check:

- `/api/live`
- `/api/ready`
- `/api/admin/observability/summary`
- `/api/backup/status`

Run one manual backup and verify the manifest before promoting.
