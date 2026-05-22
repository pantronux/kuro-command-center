# Provider Registry Add-on: Ollama Local Provider Adapter

This add-on makes Ollama available as an optional local provider behind the
Provider Registry V2. It is disabled by default and must not replace Gemini or
other configured cloud providers unless explicitly selected.

## What It Is For

- Local/private summarization drafts.
- PDF or document preprocessing drafts.
- Lightweight intent classification.
- Requirement extraction drafts.
- QA draft generation.
- Budget-saving or offline-assisted workflows.

Ollama should not be treated as a current-knowledge source unless paired with
Kuro's RAG, uploaded documents, or web grounding.

## Enablement

Set the provider registry and Ollama flags in `.env`:

```env
KURO_PROVIDER_REGISTRY_V2_ENABLED=true
KURO_OLLAMA_ENABLED=true
KURO_MODEL_OLLAMA_LOCAL=qwen
KURO_OLLAMA_BASE_URL=http://localhost:11434
```

Optional OpenAI-compatible mode:

```env
KURO_OLLAMA_USE_OPENAI_COMPAT=true
KURO_OLLAMA_OPENAI_BASE_URL=http://localhost:11434/v1
```

Automatic local routing remains disabled unless this is set:

```env
KURO_LOCAL_MODEL_ROUTING_ENABLED=true
```

## Environment Variables

| Env key | Default | Purpose |
| --- | --- | --- |
| `KURO_OLLAMA_ENABLED` | `false` | Enables local provider availability. |
| `KURO_OLLAMA_BASE_URL` | `http://localhost:11434` | Native Ollama API base URL. |
| `KURO_OLLAMA_OPENAI_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible API base URL. |
| `KURO_OLLAMA_TIMEOUT_S` | `60` | Non-streaming HTTP timeout. |
| `KURO_OLLAMA_STREAM_TIMEOUT_S` | `120` | Streaming HTTP timeout. |
| `KURO_OLLAMA_DEFAULT_MODEL` | `qwen` | Local default model name. |
| `KURO_MODEL_OLLAMA_LOCAL` | `qwen` | Provider Registry alias target for `ollama_local`. |
| `KURO_OLLAMA_USE_OPENAI_COMPAT` | `false` | Uses `/v1/chat/completions` instead of native `/api/chat`. |
| `KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST` | `false` | Allows public model inventory only when explicitly enabled. |
| `KURO_LOCAL_MODEL_ROUTING_ENABLED` | `false` | Allows automatic local fallback/routing for safe tasks. |

## Capabilities

- Provider alias: `ollama_local`
- Provider id: `ollama`
- Display name: `Local Ollama`
- Supports chat generation.
- Supports native Ollama streaming.
- Supports OpenAI-compatible non-streaming generation.
- Treats structured output as best-effort only.
- Does not execute tools directly.

## Unsupported Or Limited

- No direct tool execution.
- OpenAI-compatible streaming returns a safe unsupported-streaming event.
- Structured output is parsed only if the model returns valid JSON; it is not
  trusted blindly.
- No real Ollama call is made during app startup.
- Missing Ollama server returns controlled unavailable/timeout errors.

## Privacy And Safety

Local inference can reduce cloud exposure, but local model output is still
untrusted draft material. Do not use it as a final answer for compliance,
legal, security-sensitive tool decisions, market current-data analysis, or
enterprise QA reasoning without a grounded validation step.

Public `/api/models` exposes only safe alias metadata. It does not expose the
Ollama base URL or raw local model inventory. Admin routes expose operational
health for troubleshooting.

## Admin Routes

- `GET /api/admin/providers/ollama/health`
- `GET /api/admin/providers/ollama/models`
- `POST /api/admin/providers/ollama/smoke-test`

The smoke test uses the fixed harmless prompt:

```text
Reply with exactly: ok
```

## Troubleshooting

- **Server not running**: start Ollama with `ollama serve`; health returns
  `connection_error` while unavailable.
- **Model not pulled**: run `ollama pull qwen` or update
  `KURO_MODEL_OLLAMA_LOCAL` to an installed model.
- **Timeout**: increase `KURO_OLLAMA_TIMEOUT_S` or
  `KURO_OLLAMA_STREAM_TIMEOUT_S`, or use a smaller model.
- **Invalid JSON**: structured output remains `None`; downstream validation or
  repair must handle it.
- **Low VRAM/RAM**: choose a smaller local model and keep local routing off for
  critical tasks.

## Manual Smoke Test

```bash
curl http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen",
    "messages": [
      {"role": "user", "content": "Reply with exactly: ok"}
    ],
    "stream": false
  }'
```

The CI test suite does not make this real call; it uses mocks.
