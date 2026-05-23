# Enterprise Pilot

Use this profile for a small customer or internal enterprise pilot.

## Profile

```bash
KURO_DEPLOYMENT_PROFILE=enterprise-pilot
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
KURO_BACKUP_ENABLED=true
```

Recommended setup:

```bash
cp .env.production.example .env
```

Fill secrets only in `.env`. Keep `OPENCLAW_ENABLED=false` unless the OpenClaw
daemon is deployed and reachable.

## Go-Live Gate

Before go-live:

- Confirm `.env` contains real secrets and `.env.example` contains placeholders only.
- Confirm `/api/ready` is healthy.
- Confirm admin login works.
- Run a manual backup.
- Perform restore verification on a non-production copy.
- Review `docs/deployment/incident_response.md`.

If a stable subsystem misbehaves during pilot, rollback that subsystem by
flipping its specific feature flag to `false` and restarting. Keep the flag in
place as an operational safety switch.

## Pilot Boundaries

Keep admin and observability routes behind authenticated access. Do not expose
Phoenix or admin endpoints directly to the public internet.
