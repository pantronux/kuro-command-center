# Enterprise Refactor Phase 5 Provider Registry V2

Phase 5 adds an optional provider/model registry for Gemini, OpenAI, Anthropic, DeepSeek, and future adapters. Existing Gemini behavior remains the default because `KURO_PROVIDER_REGISTRY_V2_ENABLED` remains `false`.

## Flag Behavior

- `KURO_PROVIDER_REGISTRY_V2_ENABLED=false` keeps legacy Gemini/chat streaming paths unchanged.
- Provider Registry V2 routes are mounted additively and expose safe disabled state when the flag is off.
- Chat V2 uses Provider Registry V2 only when both `KURO_CHAT_V2_ENABLED=true` and `KURO_PROVIDER_REGISTRY_V2_ENABLED=true`.
- Provider API keys are optional. Missing keys or SDKs mark providers unavailable instead of breaking startup.

## Package

Added package:

```text
kuro_backend/providers/
```

Modules:

- `schemas.py` - `ProviderRequest`, `ProviderResponse`, `ProviderStreamEvent`, usage, status, health, and alias models.
- `registry.py` - provider availability, model alias resolution, fallback routing, health, and public model snapshots.
- `router.py` - admin and public FastAPI routes.
- `base.py` - provider base class and stream event helpers.
- `gemini_provider.py` - Gemini adapter using `google-genai` only when configured.
- `openai_provider.py` - OpenAI adapter using the SDK only when installed/configured.
- `anthropic_provider.py` - Anthropic adapter using the SDK only when installed/configured.
- `deepseek_provider.py` - OpenAI-compatible HTTP adapter only when key and base URL are configured.
- `errors.py` - registry, alias, availability, and safety-refusal exceptions.
- `usage.py` - lightweight usage estimation helpers.
- `streaming.py` - provider stream collection helpers.

The pre-existing singular package `kuro_backend/provider/` is not removed or replaced.

## Model Aliases

Aliases are resolved lazily from settings/env:

- `gemini_fast` -> `KURO_MODEL_GEMINI_FAST`, default `gemini-3-flash-preview`
- `openai_nano` -> `KURO_MODEL_OPENAI_NANO`, default `gpt-5.4-nano`
- `claude_fast` -> `KURO_MODEL_CLAUDE_FAST`, default `claude-haiku-4-5`
- `deepseek_fast` -> `KURO_MODEL_DEEPSEEK_FAST`, default `deepseek-v4-flash`

Aliases are public-safe handles. The actual model ID is never treated as a secret, but API keys and internal configuration are never returned by public routes.

## Provider Status

Provider status includes:

- `available`
- `reason`
- `configured`
- `dependency_available`
- capability flags for streaming, tools, and structured output

Common reasons:

- `available`
- `missing_api_key`
- `unavailable_dependency`
- `missing_base_url`
- `disabled`

## Routing

`ProviderRegistryV2.route_generate()` and `route_stream()` support:

- primary model alias
- fallback aliases
- timeout for generation
- retry count for non-safety failures
- no blind retry on `ProviderSafetyRefusal`

DeepSeek is available only with a configured API key and `KURO_DEEPSEEK_BASE_URL` or `DEEPSEEK_BASE_URL`.

## APIs

Admin-only:

```text
GET /api/admin/providers
GET /api/admin/providers/health
```

Public-safe:

```text
GET /api/models
```

`/api/models` returns only enabled public aliases and display names. It does not expose API keys, raw provider credentials, or secret-bearing configuration.

## Chat V2 Integration

The additive Chat V2 token stream checks Provider Registry V2 only after Chat V2 has already been enabled. If Provider Registry V2 routing fails, Chat V2 logs a warning and falls back to the legacy stream path.

This phase does not replace `/api/chat` or `/api/chat/stream`.

## Verification

Phase 5 adds `tests/test_provider_registry_v2.py` covering:

- registry disabled by default
- missing keys do not break startup
- missing SDKs do not break startup
- model aliases resolve from env/settings
- public models route is safe
- admin provider health requires admin
- mocked provider generation
- mocked provider streaming
- fallback provider routing
- legacy Gemini path when flag is false
- Chat V2 provider registry integration when both flags are enabled

Acceptance gate:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

The unqualified `python` command is unavailable in this environment, as recorded in the phase -1 baseline.
