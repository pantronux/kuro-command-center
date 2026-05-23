# KURO AI — Ollama Local Provider Adapter Codex Prompt

**Purpose:**  
Add Ollama as a local provider adapter for Kuro AI, including config, provider registry integration, streaming, OpenAI-compatible mode, health checks, and smoke tests.

**When to execute:**  
Run this **after Provider Registry V2 exists** or after the current major refactor batch has a stable `kuro_backend/providers/` package.  
If Provider Registry V2 does not exist yet, Codex must create this as a safe additive scaffold and keep it disabled by default.

**Default behavior:**  
Ollama must be **OFF by default** and must never break existing Gemini/provider behavior.

**Recommended commit message:**  
`Provider Registry Add-on: Ollama local provider adapter`

---

## 0. High-Level Goal

Add a local Ollama provider so Kuro can use local models such as Qwen for:

```text
- local/private summarization
- PDF/document preprocessing
- lightweight classification
- QA draft generation
- fallback/offline mode
- budget-saving mode
```

Ollama must not be treated as a source of current knowledge unless paired with RAG/web grounding.

---

## 1. Global Execution Rules

```text
1. Do not break existing provider registry.
2. Do not replace Gemini/default provider behavior.
3. Ollama must default OFF.
4. Missing Ollama server must not crash app startup.
5. Missing Ollama Python dependency must not crash app startup.
6. Use HTTP calls with explicit timeout.
7. No real Ollama calls in tests unless explicitly marked as optional local smoke.
8. Tests must use mocks/fakes by default.
9. Do not hardcode model names except safe .env defaults.
10. Do not expose internal host URLs publicly unless sanitized.
11. Admin routes may show masked/safe provider health.
12. Public routes may show only safe alias availability.
13. Do not log prompts/responses by default unless existing tracing explicitly allows it.
14. Do not leak secrets or local filesystem paths.
15. Preserve existing SSE streaming contract.
```

---

## 2. Environment Variables

Add these to `kuro_backend/config.py` / settings system and `.env.example`.

```env
# Ollama Local Provider
KURO_OLLAMA_ENABLED=false
KURO_OLLAMA_BASE_URL=http://localhost:11434
KURO_OLLAMA_OPENAI_BASE_URL=http://localhost:11434/v1
KURO_OLLAMA_TIMEOUT_S=60
KURO_OLLAMA_STREAM_TIMEOUT_S=120
KURO_OLLAMA_DEFAULT_MODEL=qwen
KURO_MODEL_OLLAMA_LOCAL=qwen
KURO_OLLAMA_USE_OPENAI_COMPAT=false
KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST=false
KURO_LOCAL_MODEL_ROUTING_ENABLED=false
```

Notes:

```text
- KURO_OLLAMA_ENABLED controls provider availability.
- KURO_LOCAL_MODEL_ROUTING_ENABLED controls whether router may pick local model automatically.
- KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST=false means public /api/models should not expose raw local model inventory unless explicitly allowed.
- KURO_MODEL_OLLAMA_LOCAL is the model alias target used by Kuro.
```

---

## 3. Provider Alias Target

Add model alias support:

```yaml
ollama_local:
  provider: ollama
  model_id_env: KURO_MODEL_OLLAMA_LOCAL
  default_model_id: qwen
  display_name: Local Ollama
  capabilities:
    - chat
    - streaming
    - local
    - private
```

Optional later aliases:

```yaml
ollama_qa_draft:
  provider: ollama
  model_id_env: KURO_MODEL_OLLAMA_QA_DRAFT
  default_model_id: qwen

ollama_summary:
  provider: ollama
  model_id_env: KURO_MODEL_OLLAMA_SUMMARY
  default_model_id: qwen
```

Do not require these optional aliases unless implemented cleanly.

---

## 4. Files to Add or Modify

Prefer this structure if Provider Registry V2 already exists:

```text
kuro_backend/providers/
  ollama_provider.py
  registry.py
  schemas.py
  router.py
  errors.py
  streaming.py
```

If `providers/` does not exist yet, create it as additive scaffold:

```text
kuro_backend/providers/
  __init__.py
  schemas.py
  base.py
  errors.py
  ollama_provider.py
```

Add tests:

```text
tests/test_provider_ollama.py
tests/test_provider_ollama_smoke_contract.py
```

Optional docs:

```text
docs/enterprise_refactor/provider_ollama_adapter.md
```

Update if present:

```text
.env.example
SYSTEM_MAP.md
docs/enterprise_refactor/17_codex_execution_summary.md
```

Only update SYSTEM_MAP after tests pass.

---

## 5. Provider Interface Requirements

If existing provider schemas exist, adapt to them. Otherwise implement compatible minimal schemas.

### ProviderRequest

Must support:

```python
class ProviderRequest:
    messages: list
    system_instruction: str | None
    model_alias: str | None
    model_id: str | None
    temperature: float | None
    max_output_tokens: int | None
    tools: list | None
    structured_output_schema: dict | None
    metadata: dict | None
    trace_id: str | None
```

### ProviderResponse

Must support:

```python
class ProviderResponse:
    provider: str
    model_id: str
    content: str
    structured: object | None
    raw: object | None
    usage: dict
    latency_ms: int | float
    finish_reason: str | None
    safety: dict | None
    grounding: dict | None
    trace_id: str | None
```

### ProviderStreamEvent

Must support:

```python
class ProviderStreamEvent:
    event_type: str
    delta: str | None
    content: str | None
    tool_call: dict | None
    usage: dict | None
    raw: object | None
    error: str | None
    done: bool
    trace_id: str | None
```

---

## 6. Ollama Native API Integration

Implement native Ollama `/api/chat`.

### Generate

Endpoint:

```text
POST {KURO_OLLAMA_BASE_URL}/api/chat
```

Payload shape:

```json
{
  "model": "qwen",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "stream": false,
  "options": {
    "temperature": 0.2,
    "num_predict": 1024
  }
}
```

Expected response shape example:

```json
{
  "model": "qwen",
  "created_at": "...",
  "message": {
    "role": "assistant",
    "content": "..."
  },
  "done": true
}
```

### Stream

Payload:

```json
{
  "model": "qwen",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "stream": true,
  "options": {
    "temperature": 0.2,
    "num_predict": 1024
  }
}
```

Stream mapping:

```text
Ollama chunk message.content -> ProviderStreamEvent(event_type="token", delta=...)
Ollama done true -> ProviderStreamEvent(event_type="done", done=True)
Error -> ProviderStreamEvent(event_type="error", error=...)
```

---

## 7. OpenAI-Compatible Ollama Mode

If `KURO_OLLAMA_USE_OPENAI_COMPAT=true`, support OpenAI-compatible endpoint:

```text
{KURO_OLLAMA_OPENAI_BASE_URL}/chat/completions
```

But do not require OpenAI SDK. Prefer direct HTTP unless the existing provider framework already uses an OpenAI-compatible client safely.

Request shape:

```json
{
  "model": "qwen",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.2,
  "max_tokens": 1024,
  "stream": false
}
```

Streaming mode should map SSE chunks into `ProviderStreamEvent`.

If OpenAI-compatible streaming is too risky, keep native streaming implemented and return a clear safe error for OpenAI-compatible streaming. Do not leave `NotImplementedError`.

---

## 8. Structured Output Support

Ollama supports JSON-like output for some models and configurations. Implement cautious support:

```text
- If ProviderRequest.structured_output_schema exists:
  - Prefer deterministic instruction + JSON-only response.
  - If native format/schema is supported by current implementation, pass it safely.
  - Otherwise, request JSON output and validate downstream.
- Never assume local model will obey schema perfectly.
- Always pass through existing structured output validator if available.
```

If unsupported:

```text
Return ProviderResponse.structured=None
content=<raw content>
finish_reason="schema_not_guaranteed"
```

Do not crash.

---

## 9. Tool Calling Support

For now:

```text
- supports_tools=false by default unless safely detected.
- Do not wire Ollama to execute tools directly.
- Tool execution must remain governed by Kuro Tool Runtime V2.
```

If a model emits tool-like JSON, treat it as text unless routed through the governed tool policy.

---

## 10. Health Check

Implement:

```python
OllamaProvider.health_check()
```

Checks:

```text
- KURO_OLLAMA_ENABLED
- base URL configured
- GET /api/tags reachable
- timeout respected
- model list retrieved
- configured default model exists if list available
```

Health status examples:

```json
{
  "provider": "ollama",
  "enabled": false,
  "status": "disabled",
  "base_url": "http://localhost:11434",
  "model_aliases": ["ollama_local"]
}
```

```json
{
  "provider": "ollama",
  "enabled": true,
  "status": "unavailable",
  "reason": "connection_error",
  "base_url": "http://localhost:11434"
}
```

```json
{
  "provider": "ollama",
  "enabled": true,
  "status": "ok",
  "models": ["qwen"],
  "default_model": "qwen"
}
```

Public endpoints must not expose local model inventory unless `KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST=true`.

---

## 11. Admin Routes

Add if provider admin routes exist:

```text
GET /api/admin/providers/ollama/health
GET /api/admin/providers/ollama/models
POST /api/admin/providers/ollama/smoke-test
```

Rules:

```text
- Admin-only.
- No prompts from users in smoke-test by default.
- Smoke test prompt must be harmless and short:
  "Reply with exactly: ok"
- Smoke test must be skipped or return unavailable if Ollama disabled.
- Do not expose raw stack traces.
```

If general provider admin route exists, integrate there instead.

---

## 12. Public Routes

If `/api/models` exists:

```text
- Include ollama_local only if KURO_OLLAMA_ENABLED=true.
- Do not expose raw base URL.
- Do not expose raw model inventory unless explicitly allowed.
- Display safe label: "Local Ollama"
```

If `/api/capabilities` exists:

```text
- Show local_provider_available: true/false
- Do not expose local host details publicly.
```

---

## 13. Model Routing Integration

Do not enable automatic local routing by default.

When `KURO_LOCAL_MODEL_ROUTING_ENABLED=true`, allow task router to choose Ollama for low-risk local tasks:

```text
- document_chunk_summary
- pdf_summary_draft
- intent_classification
- requirement_draft_extraction
- qa_draft_generation
- formatting
```

Do not route these to Ollama automatically unless specifically enabled:

```text
- final enterprise QA reasoning
- market current-data analysis
- compliance/legal final answer
- security-sensitive tool decision
- high-risk agent action
```

Suggested routing metadata:

```yaml
document_chunk_summary:
  primary: ollama_local
  fallback: gemini_fast

qa_reasoning:
  primary: claude_fast
  fallback: openai_nano
  local_allowed: false

market_analysis:
  primary: gemini_fast
  requires_grounding: true
  local_allowed: false
```

---

## 14. QA Pipeline Integration Suggestion

If QA Playground exists, add optional cost-saving mode:

```text
qa_pipeline.cost_saver:
  document_summary -> ollama_local
  requirement_draft_extraction -> ollama_local
  qa_reasoning -> claude_fast or openai_nano
  validation -> deterministic
```

Rules:

```text
- Ollama output must be treated as draft.
- Cloud reasoning model must receive selected excerpts or structured requirements, not blind summary only.
- Test case final output must pass schema validator.
```

Do not implement full QA pipeline in this prompt unless already present. Only add routing hooks/config where safe.

---

## 15. Tests to Add

Create:

```text
tests/test_provider_ollama.py
tests/test_provider_ollama_smoke_contract.py
```

### Required tests

#### TC-OLLAMA-001 — Disabled by default

Expected:

```text
KURO_OLLAMA_ENABLED=false by default.
Provider registry does not route to Ollama.
App startup does not contact Ollama.
```

#### TC-OLLAMA-002 — Missing Ollama server safe

Setup:

```text
KURO_OLLAMA_ENABLED=true
KURO_OLLAMA_BASE_URL=http://127.0.0.1:9
```

Expected:

```text
health_check returns unavailable/connection_error.
App does not crash.
```

#### TC-OLLAMA-003 — Mocked /api/tags health ok

Mock:

```json
{
  "models": [
    {"name": "qwen", "model": "qwen"}
  ]
}
```

Expected:

```text
health_check returns ok.
default model qwen recognized.
```

#### TC-OLLAMA-004 — Mocked native /api/chat generate

Mock response:

```json
{
  "model": "qwen",
  "message": {"role": "assistant", "content": "hello"},
  "done": true
}
```

Expected:

```text
ProviderResponse.provider == "ollama"
ProviderResponse.model_id == "qwen"
ProviderResponse.content == "hello"
```

#### TC-OLLAMA-005 — Mocked native streaming maps tokens

Mock chunks:

```json
{"message": {"content": "he"}, "done": false}
{"message": {"content": "llo"}, "done": false}
{"done": true}
```

Expected:

```text
ProviderStreamEvent token he
ProviderStreamEvent token llo
ProviderStreamEvent done
```

#### TC-OLLAMA-006 — Timeout handled safely

Setup:

```text
Mock request timeout.
```

Expected:

```text
Provider returns safe provider_unavailable/provider_timeout error.
No raw stack trace exposed.
```

#### TC-OLLAMA-007 — Public /api/models safe

Expected:

```text
No base URL.
No raw localhost URL.
No full local model inventory unless KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST=true.
```

#### TC-OLLAMA-008 — Admin health route protected

Expected:

```text
Non-admin 401/403.
Admin can access health.
```

#### TC-OLLAMA-009 — OpenAI-compatible mode request mapping

Setup:

```text
KURO_OLLAMA_USE_OPENAI_COMPAT=true
Mock /chat/completions response.
```

Expected:

```text
ProviderResponse normalized correctly.
```

#### TC-OLLAMA-010 — Tool calls disabled by default

Expected:

```text
Ollama provider does not execute tool calls directly.
Tool-like output remains text unless governed Tool Runtime handles it.
```

#### TC-OLLAMA-011 — Structured output not trusted blindly

Setup:

```text
Request structured_output_schema.
Mock invalid JSON response.
```

Expected:

```text
Provider does not crash.
Structured field is None or validator reports invalid.
Downstream repair may handle if enabled.
```

#### TC-OLLAMA-012 — Local routing disabled by default

Expected:

```text
Even if Ollama enabled, router does not automatically route local tasks unless KURO_LOCAL_MODEL_ROUTING_ENABLED=true.
```

---

## 16. Optional Local Manual Smoke Test

This is manual, not required in CI.

Precondition:

```bash
ollama serve
ollama pull qwen
```

Command:

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

Expected:

```text
Response contains message.content with ok or close equivalent.
```

If Kuro admin route exists:

```text
POST /api/admin/providers/ollama/smoke-test
```

Expected:

```json
{
  "success": true,
  "provider": "ollama",
  "status": "ok"
}
```

If Ollama is not running:

```json
{
  "success": false,
  "error": {
    "code": "provider_unavailable"
  }
}
```

---

## 17. Final Smoke Test Commands

After implementation:

```bash
python -m compileall kuro_backend main.py
pytest tests/test_provider_ollama.py -x --tb=short
pytest tests/test_provider_ollama_smoke_contract.py -x --tb=short
pytest tests/ -x --tb=short
```

If `ruff` exists:

```bash
ruff check .
```

---

## 18. Documentation Updates

Create:

```text
docs/enterprise_refactor/provider_ollama_adapter.md
```

Include:

```text
- What Ollama provider is for
- How to enable it
- Required env vars
- Supported capabilities
- Unsupported capabilities
- Privacy implications
- Cost-saving mode usage
- Why Ollama should not be used as current-knowledge source without RAG/web grounding
- Troubleshooting:
  - server not running
  - model not pulled
  - timeout
  - invalid JSON
  - low VRAM
```

Update `.env.example`.

Update `SYSTEM_MAP.md` after tests pass:

```text
- provider module
- env vars
- admin routes
- tests
- risks/blind spots
```

---

## 19. Acceptance Criteria

```text
[ ] Ollama disabled by default.
[ ] Missing Ollama server does not crash startup.
[ ] Mocked native generate works.
[ ] Mocked native stream works.
[ ] OpenAI-compatible mode is supported or safely disabled.
[ ] Admin health route protected.
[ ] Public model route safe.
[ ] Local routing disabled by default.
[ ] Tool calls not executed directly by Ollama.
[ ] Structured output not trusted blindly.
[ ] Tests pass.
[ ] .env.example updated.
[ ] Documentation added.
[ ] SYSTEM_MAP updated after tests pass.
```

---

## 20. Stop Conditions

Stop and do not continue if:

```text
- Existing Gemini/default provider path breaks.
- Existing /api/chat/stream breaks.
- App startup requires Ollama to be running.
- Public route exposes localhost/base URL or raw local model list unexpectedly.
- Tests make real Ollama calls by default.
- Provider code contains NotImplementedError/pass/placeholder behavior.
- Ollama tool-like output can trigger tools without governance.
```

---

## 21. Codex Final Instruction

```text
Implement Ollama as an optional, safe, local provider adapter.

Prefer additive changes.
Keep it disabled by default.
Do not break existing providers.
Mock all tests.
Add smoke tests.
Update docs and .env.example.
Run compileall and pytest.
```
