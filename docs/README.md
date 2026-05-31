# Kuro Command Center

Physical app folder: `/home/kuro/projects/kuro-command-center`

Role: operational and admin control room.

Primary route:

- `/command-center`

Port: `8444`

KCC owns Market Sentinel, Telegram Command Center, ingestion operations, runtime/provider/storage/memory health, backup/restore, observability, OpenClaw controls, and feature flags. It does not own PhD research state or raw KRC research history.

KCC inspects Knowledge ingest jobs through the Kuro Knowledge HTTP API at `http://127.0.0.1:8088`.

## Local Checks

```bash
cd /home/kuro/projects/kuro-command-center
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```
