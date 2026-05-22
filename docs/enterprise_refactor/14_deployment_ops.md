# Enterprise Refactor Phase 12: Deployment And Ops

Phase 12 adds small-enterprise deployment guidance and safer operational
surfaces without requiring Kubernetes.

## Added

- Deployment profiles:
  - `local-dev`
  - `single-vm`
  - `docker-compose`
  - `staging`
  - `enterprise-pilot`
- Docs under `docs/deployment/`.
- Expanded `.env.example` with placeholder-only provider, Telegram, Serper,
  OpenClaw, database path, feature flag, model alias, security, observability,
  and backup settings.
- Public-safe health endpoints:
  - `GET /api/live`
  - `GET /api/ready`
  - `GET /api/health`
- Secret-safe startup validation.
- Backup health metadata and restore verification runbook.
- `docker-compose.yml` with an app service and optional Phoenix profile.

## Safety Notes

- Startup validation logs variable names only, never values.
- Provider keys, Telegram tokens, OpenClaw keys, and JWT values stay out of
  committed files.
- Public health endpoints avoid memory stats, DB paths, raw backup paths, and
  internal topology.
- Detailed backup and observability views remain admin-only.

## Local Dev Compatibility

Local development still needs only a valid `JWT_SECRET_KEY` at import/startup.
Missing provider, Telegram, Serper, OpenClaw, and optional feed keys produce
warnings, not startup failures.

## Verification

Target commands:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/test_enterprise_ops.py -q
pytest tests/ -x --tb=short
```
