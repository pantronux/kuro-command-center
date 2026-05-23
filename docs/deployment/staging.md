# Staging

Use staging for release smoke tests before promoting a stable runtime profile to
a pilot.

## Profile

```bash
KURO_DEPLOYMENT_PROFILE=staging
KURO_PLAYGROUND_ENABLED=true
KURO_PLAYGROUND_API_ENABLED=true
KURO_V2_STRICT_MODE=true
KURO_PROVIDER_ROUTER_ENABLED=true
KURO_DEV_MODE=false
KURO_ENTERPRISE_REFACTOR_ENABLED=true
KURO_MEMORY_V3_ENABLED=true
KURO_STORAGE_V2_ENABLED=true
KURO_CHAT_V2_ENABLED=true
KURO_MARKET_SENTINEL_V2_ENABLED=true
KURO_TELEGRAM_V2_ENABLED=true
KURO_PROVIDER_REGISTRY_V2_ENABLED=true
KURO_AGENT_TOOLS_V2_ENABLED=true
KURO_TASKS_V2_ENABLED=true
KURO_DEEP_RESEARCH_V2_ENABLED=true
KURO_WEB_SEARCH_V2_ENABLED=true
KURO_ADMIN_SETTINGS_V2_ENABLED=true
KURO_API_V2_ENABLED=true
KURO_ENTERPRISE_OBSERVABILITY_ENABLED=true
```

You can also start from `.env.production.example` and change
`KURO_DEPLOYMENT_PROFILE=staging`.

Use non-production Telegram chats and non-production provider keys where
available.

If a regression appears, rollback by setting the failing subsystem flag to
`false` and restarting the service. Do not use `KURO_DEV_MODE=true` as a
production rollback because it bypasses development-only safeguards.

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
