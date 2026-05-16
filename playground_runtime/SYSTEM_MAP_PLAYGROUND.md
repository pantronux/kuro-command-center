# Kuro Playground Runtime — SYSTEM_MAP_PLAYGROUND

> Private lab documentation for Master Pantronux only. This file is intentionally
> isolated from `SYSTEM_MAP.md` because `playground_runtime/` is a forensic KPR
> lab, not part of the general Kuro production surface.

## Executive Summary

Kuro Playground Runtime is a separate experimental lane for controlled KPR
execution, forensic evidence capture, schema normalization inspection, and
cross-provider comparison. It exists so Pantronux can study model behavior
without coupling the work to `kuro_backend` production flows.

The Playground has three defining properties:

1. **Isolation first**: host app may mount Playground routes, but
   `playground_runtime/` must not import `kuro_backend`.
2. **Forensic persistence first**: raw provider evidence is stored verbatim
   before canonical normalization.
3. **Private access first**: the dashboard Playground mode and tutorial surface
   are restricted to `Pantronux`.

## Why This Exists

The main Kuro system is a production assistant. Playground is a private lab.
Those are different jobs.

Playground exists to support:

- forensic inspection of provider outputs;
- comparative testing with the same prompt across multiple providers;
- ontology reconstruction from isolated traces;
- schema drift detection when provider payloads change;
- safe experimentation without altering `kuro_backend` architecture.

This is why the docs are duplicated privately instead of merged into the main
system map. The intended reader is Pantronux operating the lab, not general app
users.

## Purpose of KPR / Forensic Playground

Within this repository, KPR is the isolated runtime lane used for:

- creating execution sessions by mode;
- invoking one or more providers with the same prompt;
- storing execution evidence in a Playground-only database;
- projecting provider payloads into `CanonicalInferenceTrace`;
- reconstructing ontology artifacts from stored traces;
- exporting Playground-specific reports and forensic outputs.

## Isolation Model

The isolation contract is enforced by:

- `playground_runtime/governance/boundary_validator.py`
  - rejects forbidden imports and production coupling;
- `playground_runtime/governance/isolation_gate.py`
  - constrains DB path and runtime references;
- `playground_runtime/service.py`
  - validates imports before wiring dependencies;
- `main.py`
  - mounts Playground one-way when enabled, but Playground never reaches back
    into `kuro_backend`.

Key rule:

- Host app can import Playground.
- Playground cannot import `kuro_backend`.

## Entrypoints and Routing

Primary entrypoints:

- `main.py`
  - conditionally mounts `/api/playground/*` through
    `_mount_playground_router_if_enabled()`;
- `playground_runtime/api/router.py`
  - declares isolated Playground API routes;
- `web_interface/templates/index.html`
  - provides Playground dashboard panel and entry controls;
- `web_interface/static/js/app.js`
  - switches runtime mode and calls Playground APIs.

Routes currently relevant to the private lab:

- `GET /api/playground/health`
- `GET /api/playground/providers`
- `POST /api/playground/sessions`
- `POST /api/playground/executions`
- `POST /api/playground/comparative-executions`
- `POST /api/playground/ontology/reconstruct`
- `POST /api/playground/reports/{format}`
- `POST /api/playground/snapshots`
- `POST /api/playground/snapshots/{snapshot_id}/verify`
- `GET /api/playground/sessions/{session_id}/forensic-view`
- `POST /api/playground/datasets/executions`
- `GET /api/playground/sessions/{session_id}/traces`
- `GET /api/playground/sessions/{session_id}/history`
- `GET /api/playground/sessions/{session_id}/integrity-overview`
- `GET /api/playground/sessions/{session_id}/executions/{execution_id}/integrity-detail`
- `POST /api/playground/sessions/{session_id}/integrity/refresh`
- `GET /api/playground/snapshots/{snapshot_id}/trust-summary?session_id=...`
- `POST /api/playground/sessions/{session_id}/exports/forensic-bundle`
- `GET /api/playground/sessions/{session_id}/lineage`
- `GET /playground/tutorial`
- `GET /api/playground/tutorial/content`

The private documentation entrypoint is `/playground/tutorial`.

## Access Model

Playground access is intentionally narrower than general dashboard access.

- backend gate: `main.py::require_admin_user()`
- effective policy: only `ADMIN_USERNAME`, which is currently `Pantronux`
- non-authorized users receive `403 Forbidden`

This applies to:

- Playground API access;
- Playground tutorial HTML route;
- Playground tutorial markdown content API.

## Configuration Model

Configuration lives in `playground_runtime/config.py`.

Two namespaces are intentionally separated:

- runtime flags: `KURO_PLAYGROUND_*`
- provider credentials and models: `PLAYGROUND_*`

Important runtime flags:

- `KURO_PLAYGROUND_ENABLED`
- `KURO_PLAYGROUND_API_ENABLED`
- `KURO_PLAYGROUND_RESEARCH_MODE`
- `KURO_PLAYGROUND_FORENSIC_MODE`
- `KURO_PLAYGROUND_COMPARATIVE_MODE`
- `KURO_PLAYGROUND_ONTOLOGY_MODE`
- `KURO_PLAYGROUND_TELEMETRY_ENABLED`
- `KURO_PLAYGROUND_EPISTEMIC_DIFF`
- `KURO_PLAYGROUND_HALLUCINATION_ANALYZER`
- `KURO_PLAYGROUND_RAW_EVIDENCE_RETENTION_DAYS`
- `KURO_PLAYGROUND_DB_PATH`

Provider activation is canonical-only in this phase. Multi-alias
`openai_compat` support was intentionally skipped.

## Provider Model

Only six canonical providers are supported:

1. `openai`
2. `gemini`
3. `anthropic`
4. `deepseek`
5. `ollama`
6. `openai_compat`

Relevant modules:

- `playground_runtime/providers/registry.py`
- `playground_runtime/providers/router.py`
- `playground_runtime/providers/adapters/*`

Operational notes:

- `PLAYGROUND_<PROVIDER>_API_KEY` activates API-key providers;
- `PLAYGROUND_OLLAMA_BASE_URL` activates `ollama`;
- `openai_compat` remains canonical-only, no alias fan-out;
- comparative execution requires at least two active providers and respects
  `KURO_PLAYGROUND_MAX_CONCURRENT_PROVIDERS`.

Local Ollama setup (OpenAI-compatible path):

- `export PLAYGROUND_OLLAMA_BASE_URL=http://localhost:11434/v1`
- `export PLAYGROUND_OLLAMA_MODEL_NAME=qwen3:4b`
- verify native Ollama tags:
  `curl http://localhost:11434/api/tags`
- verify model listing:
  `curl http://localhost:11434/v1/models`
- verify chat completion:
  `curl http://localhost:11434/v1/chat/completions ...`

Expected validation:

- `/api/tags` includes `qwen3:4b`
- `/v1/models` includes `qwen3:4b`
- `/v1/chat/completions` returns `choices[0].message.content`
- some models may also return `choices[0].message.reasoning`

Security note:

- Do not expose Ollama port `11434` publicly without strict network controls.
- Treat `choices[0].message.reasoning` as a model-generated visible reasoning artifact.
- Treat Gemini `thought_signature` as an opaque provider reasoning signature.
- Neither field is treated as guaranteed true internal chain-of-thought.

Gemini note:

- the adapter uses Google's OpenAI-compatible endpoint under
  `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`;
- this replaced an earlier broken `/v1/chat/completions` call that returned
  `404 Not Found`.

## Runtime Modes

Session modes are resolved in `playground_runtime/modes/`.

Current modes:

1. `research`
   - baseline isolated execution and storage for prompt/model inspection.
2. `forensic`
   - emphasizes trace preservation, raw evidence review, and normalization
     warnings.
3. `comparative`
   - runs the same prompt across multiple providers and stores epistemic diff
     records.
4. `ontology`
   - supports graph reconstruction from stored canonical traces.

The dashboard provider checklist exists because one prompt often needs to be
run against several models in one pass. One selected provider triggers single
execution. Two or more providers trigger comparative execution automatically.

## Service Orchestration

Main orchestration entry:

- `playground_runtime/service.py::PlaygroundRuntimeService`

Core dependencies wired there:

- settings;
- boundary validator and isolation gate;
- `PlaygroundDB`;
- provider registry and router;
- normalization registry;
- evidence store;
- telemetry bridge;
- ontology reconstruction;
- report export.
- forensic bundle export.

Important methods:

- `create_session()`
- `execute_single()`
- `execute_comparative()`
- `reconstruct_ontology()`
- `build_and_export_report()`
- `create_snapshot()`
- `verify_snapshot()`
- `build_forensic_view()`
- `execute_dataset()`
- `build_integrity_overview()`
- `build_execution_trust_record()`
- `build_snapshot_trust_summary()`
- `build_session_timeline_integrity()`
- `build_transformation_lineage()`
- `export_forensic_bundle()`
- `list_session_traces()`

## DB Schema and Persistence Flow

Persistence lives in:

- `playground_runtime/db/playground_db.py`
- migrations:
  - `playground_runtime/db/migrations/001_initial_schema.sql`
  - `playground_runtime/db/migrations/002_forensic_integrity_expansion.sql`
  - `playground_runtime/db/migrations/003_forensic_trust_workflow.sql`

Database design goals:

- keep Playground evidence isolated from production DBs;
- store raw provider output immutably;
- make canonical traces queryable and exportable.

Execution invariants:

1. insert `model_executions`
2. insert `raw_evidence` verbatim
3. normalize from a copied payload
4. insert `canonical_traces`
5. optionally persist hallucination or comparative diff artifacts

Additional forensic integrity layers:

1. write `artifact_integrity` rows for raw/canonical/report/snapshot/timeline/export artifacts
2. write `transformation_manifest` rows for normalization lineage
3. write `chain_of_custody` lifecycle events
4. persist `evidence_snapshots` and verification status
5. persist `provider_capabilities` per session
6. persist `semantic_divergence` structured comparison rows
7. persist `ontology_entities` and `ontology_relationships`
8. persist `dataset_executions` summaries for synchronous batch runs

Why raw-first matters:

- forensic review depends on the untouched provider payload;
- normalization bugs can be fixed later without losing original evidence;
- schema drift is visible because canonical projection and raw storage are
  separate.

Retention note:

- `purge_expired_evidence(retention_days: int) -> int` exists as a skeleton in
  `playground_db.py`;
- it is not yet wired into the runtime flow.

## Normalization / Canonical Trace Flow

Relevant modules:

- `playground_runtime/schema/canonical_trace.py`
- `playground_runtime/schema/normalization_registry.py`
- `playground_runtime/schema/mappers/*`

The canonical trace contract is frozen. Mapper logic absorbs provider
differences without changing `CanonicalInferenceTrace`.

Key rules:

- raw evidence is stored in full;
- CoT-like or hidden reasoning fields are not projected into canonical traces;
- normalization warnings are attached when provider payloads surface such fields;
- schema drift is surfaced via forensic flags rather than silent coercion.

Typical signals seen in the trace layer:

- `SCHEMA_DRIFT:*`
- `NO_CANDIDATES`
- `GROUNDING_TOOL_ABSENT`
- `GROUNDING_ABSENT`

## Governance and Reasoning-Safety Constraints

Relevant modules:

- `playground_runtime/governance/reasoning_policy.py`
- `playground_runtime/governance/boundary_validator.py`
- `playground_runtime/governance/isolation_gate.py`

Reasoning-safety contract:

- no hidden reasoning exposure in canonical traces;
- raw payloads may contain more data, but trace projection must remain safe;
- warnings should be emitted when payloads include CoT-like fields;
- no-cross-import policy remains enforceable at runtime and in tests.

## UI / Dashboard Integration

Relevant files:

- `web_interface/templates/index.html`
- `web_interface/static/js/app.js`

Dashboard behavior:

- header toggle switches between `Normal` and `Playground`;
- Playground panel hides normal chat while active;
- only `Pantronux` can actually use Playground;
- session creation stores the active Playground session id in the frontend;
- provider checklist allows single or comparative execution from one prompt;
- output panel supports `Copy` and `Download`;
- `Execute` button has loading state and anti double-click behavior.

Recent UX hardening:

- clearer HTTP error printing for Playground routes;
- loading state during execution;
- output copy and file download actions;
- dedicated `Tutorial` button for private docs access.

Trust workflow UI additions:

- workflow selector (`quick`, `deep`, `academic`) in Playground quick checks;
- integrity overview panel with alert severity rendering;
- execution trust chips inside history detail:
  - Integrity
  - Snapshot
  - Schema Drift
  - Transform
- artifact trust detail drawer with four metadata sections:
  - acquisition
  - integrity
  - transformation
  - provenance
- quick actions for:
  - snapshot verification
  - forensic bundle export
  - lineage view

## Tutorial / Documentation Surface

Private documentation files:

- `playground_runtime/SYSTEM_MAP_PLAYGROUND.md`
- `playground_runtime/CHANGELOG_PLAYGROUND.md`

Private tutorial UI:

- `web_interface/templates/playground_tutorial.html`

Private documentation routes:

- `GET /playground/tutorial`
- `GET /api/playground/tutorial/content`

This surface mirrors the main tutorial mechanics but is intentionally kept
separate for private lab operations.

## Testing Surface

Primary tests around Playground include:

- `tests/test_playground_config.py`
- `tests/test_playground_boundary_validator.py`
- `tests/test_playground_db_schema.py`
- `tests/test_playground_provider_registry.py`
- `tests/test_playground_service_flow.py`
- `tests/test_playground_api.py`
- `tests/test_playground_schema_normalization.py`
- `tests/test_playground_gemini_adapter.py`
- `tests/test_main_playground_mount.py`
- `tests/test_playground_tutorial_routes.py`
- `tests/test_playground_forensic_integrity.py`
- `tests/test_playground_transformation_manifest.py`
- `tests/test_playground_chain_of_custody.py`
- `tests/test_playground_snapshot_verification.py`
- `tests/test_playground_divergence_engine.py`
- `tests/test_playground_dataset_pipeline.py`
- `tests/test_playground_rendering_modes.py`
- `tests/test_playground_integrity_trust_api.py`
- `tests/test_playground_integrity_status_mapping.py`
- `tests/test_playground_forensic_bundle_export.py`
- `tests/test_playground_integrity_history_ui_contract.py`
- `tests/test_playground_snapshot_trust_states.py`
- `tests/test_playground_session_timeline_integrity.py`

These tests cover:

- feature-flag parsing;
- import boundary enforcement;
- DB bootstrapping and evidence handling;
- provider activation and comparative constraints;
- normalization safety;
- route access control;
- tutorial route isolation;
- trust status mapping and integrity timeline drift detection;
- snapshot trust interpretation and replay compatibility states;
- forensic bundle export structure and audit trail;
- additive history payload compatibility for trust data.

## Known Current Limits

Current intentional limits in this phase:

- no multi-alias `openai_compat` support;
- tutorial renders only `SYSTEM_MAP_PLAYGROUND.md`, not changelog browsing;
- retention purge exists only as a skeleton and is not scheduled;
- provider-specific schema drift can still surface `unknown` fields in the
  canonical trace while the mapped values remain in `extra_fields`;
- Playground remains a mounted subsystem inside `main.py`, not a separate
  process.
- ZIP cleanup for exported forensic bundle artifacts is manual.

## Recent Fixes Captured by This Lab

This iteration resolved several operational issues:

1. Playground router originally returned `404` because
   `KURO_PLAYGROUND_ENABLED` and `KURO_PLAYGROUND_API_ENABLED` were missing.
2. Access was locked back to strict `Pantronux`-only enforcement.
3. Gemini execution failed because the adapter used the wrong endpoint path.
4. `Execute` gained loading state and anti double-click handling.
5. Playground output gained `Copy` and `Download` actions.
6. A private tutorial surface was added so Playground knowledge stays outside
   the main Kuro documentation stream.
7. Forensic trust workflow now exposes session/execution integrity in readable
   UI and API projections without breaking older payload contracts.
