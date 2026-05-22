# Enterprise Refactor Phase 9: API and Middleware Hardening

## Scope

Phase 9 adds an additive API V2 control layer under `kuro_backend/api_v2/`.
Existing API routes stay compatible and are not re-enveloped. The V2 layer
provides shared helpers and control-plane routes for future endpoints.

`KURO_API_V2_ENABLED` remains false by default.

## Package

- `schemas.py`: typed response, error, health, principal, and pagination models.
- `responses.py`: standard success/error envelope helpers.
- `errors.py`: standard error taxonomy and API V2 exception normalization.
- `middleware.py`: ASGI middleware for trace id, timing, request size checks,
  security headers, and rate-limit hooks.
- `authz.py`: RBAC helpers using existing auth/user data.
- `rate_limit.py`: disabled-by-default per user/IP/route-class rate limiting.
- `pagination.py`: cursor helpers for future V2 list routes.
- `openapi.py`: public OpenAPI filtering that excludes admin paths.

## Response Envelope

API V2 responses use:

```json
{
  "status": "success",
  "data": {},
  "error": null,
  "trace_id": "trace_x",
  "meta": {}
}
```

Error responses use the same envelope with:

```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "forbidden",
    "message": "Forbidden",
    "detail": null
  },
  "trace_id": "trace_x",
  "meta": {}
}
```

Standard codes:

- `unauthorized`
- `forbidden`
- `not_found`
- `validation_error`
- `feature_disabled`
- `rate_limited`
- `provider_unavailable`
- `tool_denied`
- `memory_denied`
- `internal_error`

## Middleware Behavior

`KuroAPIMiddleware` is ASGI-level middleware. It does not read or buffer response
bodies, so SSE and streaming responses keep their existing behavior.

It adds:

- `X-Trace-ID`
- `X-Response-Time-ms`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

Request-size limiting is disabled by default. Configure it with:

```bash
KURO_API_V2_REQUEST_SIZE_LIMIT_BYTES=1048576
```

Rate limiting is disabled by default. Enable with:

```bash
KURO_API_V2_RATE_LIMIT_ENABLED=true
KURO_API_V2_RATE_LIMIT_PER_MIN=120
KURO_API_V2_RATE_LIMIT_CHAT_PER_MIN=60
KURO_API_V2_RATE_LIMIT_MARKET_PER_MIN=30
KURO_API_V2_RATE_LIMIT_RESEARCH_PER_MIN=20
KURO_API_V2_RATE_LIMIT_TELEGRAM_PER_MIN=30
```

Supported route classes:

- `chat`
- `market`
- `research`
- `telegram`
- `default`

## RBAC

`authz.py` converts existing authenticated users into a `Principal`:

- `admin`: username matches `ADMIN_USERNAME` or existing registry role.
- `user`: every authenticated user.
- `auditor`: username listed in `KURO_AUDITOR_USERNAMES` or registry role.
- `service_account`: username listed in `KURO_SERVICE_ACCOUNT_USERNAMES`, starts
  with `svc_`, or registry role.

No new authentication mechanism is introduced. API V2 depends on the existing
cookie/JWT validation dependencies when mounted in `main.py`.

## Routes

- `GET /api/v2/health`
- `GET /api/v2/feature-disabled`
- `GET /api/v2/errors/provider-unavailable`
- `GET /api/v2/me`
- `GET /api/v2/admin/probe`
- `GET /api/v2/openapi/public`

The existing auth middleware still protects `/api/*` in the main app. Test apps
can mount the router directly for isolated middleware tests.

## Compatibility

Legacy route bodies are not rewritten. For non-`/api/v2` HTTP exceptions, the
exception handler returns the normal `{"detail": ...}` shape. API V2 errors are
normalized into the V2 envelope.

SSE compatibility is covered by a regression test against `/api/chat/stream`.

## Verification

Focused tests:

```bash
python3 -m compileall kuro_backend/api_v2 main.py
pytest tests/test_api_v2.py -q
```

Full acceptance check:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```
