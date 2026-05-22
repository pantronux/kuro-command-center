# Enterprise Refactor Phase 3 Memory V3 Retrieval

Phase 3 adds scoped retrieval, ranking, provenance-aware context packing, and guarded integration with `memory_coordinator`. The existing context path remains unchanged while `KURO_MEMORY_V3_ENABLED=false`.

## Flag Behavior

- `KURO_MEMORY_V3_ENABLED` still defaults to `false`.
- When disabled, `build_context_for_llm()` does not instantiate or call `MemoryV3Reader`.
- When enabled, `build_context_for_llm()` first builds the legacy context, then attempts to prepend a Memory V3 context pack.
- If Memory V3 retrieval raises, the coordinator logs a warning and returns the legacy context.
- If `chat_id` is missing, Memory V3 context injection is skipped to avoid cross-chat retrieval.

## Retrieval API

`kuro_backend/memory_v3/reader.py` now provides:

- `retrieve()`
- `retrieve_by_keyword()`
- `retrieve_by_semantic_adapter()`
- `retrieve_recent()`
- `retrieve_high_importance()`
- `retrieve_task_related()`
- `retrieve_market_signal_related()`

The legacy `read()` method remains available for basic scoped reads and admin diagnostics.

## Schemas

`kuro_backend/memory_v3/schemas.py` adds:

- `MemoryRetrievalCandidate`
- `MemoryContextPack`
- `MemoryCitation`
- `MemoryRetrievalDiagnostics`

The context pack carries sanitized prompt text, selected memory IDs, citations, grouped counts, and retrieval diagnostics.

## Ranking

Candidate ranking is deterministic and combines:

- lexical relevance
- semantic relevance when a local adapter is supplied
- recency
- confidence score
- importance score
- source reliability
- scope match strength
- conflict penalty
- deprecated status penalty
- suspicious-memory penalty

Expired and redacted records are excluded from prompt packing.

## Source Reliability

Reliability weights are assigned for:

- `direct_user_statement`
- `uploaded_file`
- `tool_result`
- `web_search`
- `market_data_provider`
- `provider_response`
- `system_config`
- `inference`
- `unknown`

Known legacy aliases such as `conversation`, `ingestion`, and `market` are normalized into the enterprise source types.

## Context Packing

The packer:

- groups memories by `memory_type`
- removes duplicate canonical keys
- collapses near-duplicate content
- includes citation IDs and source types
- includes conflict warnings
- includes freshness notes
- enforces a token budget with deterministic truncation
- sanitizes raw paths, database filenames, and secret-like values

Suspicious memories are omitted from the injected evidence text. The pack records an omission warning with the memory citation and reason instead of injecting the remembered instruction-like content.

## Anti-Poisoning

Retrieval marks suspicious content when it contains markers for:

- prompt instruction overrides
- hidden system/developer prompt requests
- safety, policy, or tool override attempts
- role override attempts
- memories that claim they must be obeyed as instructions

Suspicious content may appear in candidate diagnostics, but it is not injected as prompt instruction content.

## Telemetry

Each retrieval emits lightweight telemetry with:

- candidate count
- selected memory count
- dropped expired count
- conflict count
- suspicious memory count
- latency
- trace ID

Reads are also written to the Memory V3 access log.

## Verification

Phase 3 adds `tests/test_memory_v3_retrieval.py` covering:

- username isolation
- runtime isolation
- chat isolation where requested
- expired memory exclusion
- conflicted memory penalty
- suspicious instruction omission
- token budget enforcement
- coordinator fallback to legacy context
- secret/path sanitization

Acceptance gate:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

The unqualified `python` command is unavailable in this environment, as recorded in the phase -1 baseline.
