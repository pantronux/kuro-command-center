# Enterprise Refactor Phase 0 Feature Flags

Phase 0 introduces an enterprise control plane without replacing any existing runtime path. The default behavior remains unchanged: all new enterprise flags default to `false`, and existing chat, memory, market, Telegram, provider, API, and frontend paths continue to run as before.

This closes the audit gaps for missing enterprise feature flags, missing public-safe capability discovery, and missing safe env examples:

- `G-001` control plane
- `G-002` public-safe `/api/capabilities`
- `G-031` `.env.example`

## Flag Defaults

| Env key | Default | Purpose |
| --- | --- | --- |
| `KURO_ENTERPRISE_REFACTOR_ENABLED` | `false` | Master enterprise refactor enablement marker. |
| `KURO_MEMORY_V3_ENABLED` | `false` | Future Memory V3 path. |
| `KURO_STORAGE_V2_ENABLED` | `false` | Future Storage V2 path. |
| `KURO_CHAT_V2_ENABLED` | `false` | Future Chat V2 path. |
| `KURO_MARKET_SENTINEL_V2_ENABLED` | `false` | Future Market Sentinel V2 path. |
| `KURO_TELEGRAM_V2_ENABLED` | `false` | Future Telegram V2 path. |
| `KURO_PROVIDER_REGISTRY_V2_ENABLED` | `false` | Future provider registry path. |
| `KURO_AGENT_TOOLS_V2_ENABLED` | `false` | Future agent action/tool governance path. |
| `KURO_TASKS_V2_ENABLED` | `false` | Future durable task runtime path. |
| `KURO_DEEP_RESEARCH_V2_ENABLED` | `false` | Future deep research path. |
| `KURO_WEB_SEARCH_V2_ENABLED` | `false` | Future web search path. |
| `KURO_FRONTEND_V2_ENABLED` | `false` | Future frontend path. |
| `KURO_ADMIN_SETTINGS_V2_ENABLED` | `false` | Future admin settings path. |
| `KURO_ENTERPRISE_OBSERVABILITY_ENABLED` | `false` | Future enterprise observability path. |
| `KURO_API_V2_ENABLED` | `false` | Future API V2 path. |

## Provider Alias Settings

Provider keys are recorded as optional configuration only. Missing keys must not break startup; they only make that provider unavailable to future runtime code.

| Env key | Default |
| --- | --- |
| `GEMINI_API_KEY` | empty |
| `OPENAI_API_KEY` | empty |
| `ANTHROPIC_API_KEY` | empty |
| `DEEPSEEK_API_KEY` | empty |
| `KURO_DEFAULT_PROVIDER` | `gemini` |
| `KURO_DEFAULT_MODEL_ALIAS` | `gemini_fast` |
| `KURO_MODEL_GEMINI_FAST` | `gemini-3-flash-preview` |
| `KURO_MODEL_OPENAI_NANO` | `gpt-5.4-nano` |
| `KURO_MODEL_CLAUDE_FAST` | `claude-haiku-4-5` |
| `KURO_MODEL_DEEPSEEK_FAST` | `deepseek-v4-flash` |

Model names are treated as configurable aliases. Callers should use aliases such as `gemini_fast` rather than hardcoding concrete provider model names.

## Runtime Helpers

`kuro_backend/enterprise_flags.py` provides:

- `is_enabled(flag_name)` for known enterprise flags.
- `get_enterprise_flag_snapshot(admin=False)` for public-safe or admin-only snapshots.
- `require_feature_enabled(flag_name)` for future gated paths that need a safe disabled-feature response.

Unknown flags resolve to disabled.

## API Contracts

`GET /api/capabilities`

Returns high-level public-safe feature availability. It must not expose secrets, provider API keys, concrete model names, prompt stacks, memory namespaces, tool names, database paths, Chroma paths, or internal topology.

`GET /api/admin/enterprise-flags`

Requires the existing admin authentication helper. It returns raw enterprise flag states plus non-secret provider key presence and model alias metadata for admin operators.

## Verification

Phase 0 adds `tests/test_enterprise_feature_flags.py` covering:

- all enterprise flags default off under clean env defaults
- public capabilities response is safe
- admin enterprise flags route requires admin auth
- missing provider keys do not break config/flag import

The full acceptance gate remains:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

The unqualified `python` command is unavailable in the current environment, as recorded in the phase -1 safety baseline.
