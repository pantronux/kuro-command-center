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

Fill real secrets only in `.env`.

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
