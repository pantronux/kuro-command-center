# Docker Compose Deployment

`docker-compose.yml` provides a practical single-host deployment shape with:

- `app`
- optional `phoenix` profile
- persistent runtime, backup, and Phoenix volumes

## Setup

```bash
cp .env.example .env
chmod 600 .env
```

Fill real secrets only in `.env`. For staging-like or production-like Compose
runs, copy `.env.production.example` instead; it enables stable runtime flags
and keeps `OPENCLAW_ENABLED=false` until the daemon is deployed.

## Run App

```bash
docker compose up app
```

## Run With Phoenix Service

```bash
docker compose --profile observability up
```

If Kuro launches Phoenix in-process, keep the separate Phoenix service disabled
to avoid port contention.

## Health

```bash
curl http://127.0.0.1:8443/api/live
curl http://127.0.0.1:8443/api/ready
```
