# Single VM Deployment

Use this profile for a small production or internal pilot on one VM.

## Profile

Set:

```bash
KURO_DEPLOYMENT_PROFILE=single-vm
WORKING_DIR=/opt/kuro/runtime
KURO_BACKUP_DIR=/opt/kuro/backups
JWT_SECRET_KEY=<long random value>
```

Store `.env` outside web-accessible paths and restrict permissions:

```bash
chmod 600 .env
```

## Runtime

Run Kuro behind a reverse proxy or private network boundary. Keep Phoenix bound
to trusted networks only. Use persistent disks for:

- `WORKING_DIR`
- `KURO_BACKUP_DIR`
- `PHOENIX_WORKING_DIR`
- Chroma and upload directories

## Health

Use public-safe endpoints:

- `/api/live`
- `/api/ready`
- `/api/health`

Use admin endpoints for operational detail:

- `/api/system-status`
- `/api/backup/status`
- `/api/admin/observability/summary`
