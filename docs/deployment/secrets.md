# Secrets Hygiene

Never commit real secrets. Use `.env` or your deployment platform secret store.

## Secret Classes

- Provider keys: Gemini, OpenAI, Anthropic, DeepSeek
- Telegram tokens and webhook secrets
- JWT signing key
- Admin password hashes
- OpenClaw API key
- External feed keys such as Serper, NewsAPI, Metaculus, NVD

## Rules

- `.env.example` uses placeholders only.
- Do not print environment values in logs.
- Startup validation logs only variable names and configured/missing status.
- Rotate secrets after accidental exposure.
- Prefer separate staging and production keys.

## Rotation Checklist

1. Create the new secret in the provider console.
2. Update `.env` or the secret store.
3. Restart Kuro.
4. Verify `/api/ready`.
5. Revoke the old secret.
