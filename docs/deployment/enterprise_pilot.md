# Enterprise Pilot

Use this profile for a small customer or internal enterprise pilot.

## Profile

```bash
KURO_DEPLOYMENT_PROFILE=enterprise-pilot
KURO_API_V2_ENABLED=true
KURO_FRONTEND_V2_ENABLED=true
KURO_ENTERPRISE_OBSERVABILITY_ENABLED=true
KURO_BACKUP_ENABLED=true
```

## Go-Live Gate

Before go-live:

- Confirm `.env` contains real secrets and `.env.example` contains placeholders only.
- Confirm `/api/ready` is healthy.
- Confirm admin login works.
- Run a manual backup.
- Perform restore verification on a non-production copy.
- Review `docs/deployment/incident_response.md`.

## Pilot Boundaries

Keep admin and observability routes behind authenticated access. Do not expose
Phoenix or admin endpoints directly to the public internet.
