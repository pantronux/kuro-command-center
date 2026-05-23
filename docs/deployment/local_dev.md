# Local Development

Use this profile for one developer machine.

## Profile

Set:

```bash
KURO_DEPLOYMENT_PROFILE=local-dev
WORKING_DIR=/path/to/kuro
JWT_SECRET_KEY=<local random value>
```

Provider keys, Telegram, Serper, and OpenClaw are optional. Missing optional
keys should produce startup warnings only.

Local development intentionally keeps most enterprise/stable runtime flags off
unless a developer enables them in `.env`. Use `.env.production.example` only
when you want to mirror staging or pilot behavior locally.

## Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8443
```

Check:

```bash
curl http://127.0.0.1:8443/api/live
curl http://127.0.0.1:8443/api/ready
```

Do not commit `.env`, runtime databases, Phoenix data, Chroma data, uploads, or
backup archives.
