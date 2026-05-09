# CHANGELOG_PLAYGROUND — Kuro Playground Runtime

> Private changelog for the isolated Playground lab under `playground_runtime/`.
> This document is separate from the main `CHANGELOG.md` by design.

## [2026-05-09] Forensic Integrity Expansion and Trust Workflow UI

### New Features
- Added full forensic integrity expansion across runtime artifacts:
  - artifact hashing ledger,
  - transformation manifests,
  - chain-of-custody records,
  - evidence snapshots and verification,
  - provider capability persistence,
  - semantic divergence persistence,
  - synchronous dataset execution records.
- Added investigator-facing trust workflow surfaces:
  - integrity overview metrics,
  - execution trust detail view,
  - session timeline integrity hashing,
  - snapshot trust summary,
  - forensic bundle ZIP export,
  - transformation lineage view,
  - workflow modes: `quick`, `deep`, `academic`.

### Architecture & Backend
- Added integrity modules under `playground_runtime/integrity/`:
  - `artifact_hashing.py`
  - `transformation_manifest.py`
  - `chain_of_custody.py`
  - `evidence_snapshot.py`
  - `provenance_integrity.py`
  - `forensic_verification.py`
- Added divergence modules under `playground_runtime/divergence/`:
  - `semantic_diff.py`
  - `grounding_diff.py`
  - `claim_overlap.py`
  - `hallucination_comparison.py`
  - `provider_variance.py`
- Added provider capability catalog persistence layer:
  - `playground_runtime/providers/capabilities/__init__.py`
  - `playground_runtime/providers/capabilities/catalog.py`
- Added forensic bundle exporter:
  - `playground_runtime/export/forensic_bundle_exporter.py`
- Extended `PlaygroundRuntimeService` with trust and integrity methods:
  - `build_integrity_overview()`
  - `build_execution_trust_record()`
  - `build_snapshot_trust_summary()`
  - `build_session_timeline_integrity()`
  - `build_transformation_lineage()`
  - `export_forensic_bundle()`

### API & Contracts
- Added endpoints:
  - `GET /api/playground/sessions/{session_id}/integrity-overview`
  - `GET /api/playground/sessions/{session_id}/executions/{execution_id}/integrity-detail`
  - `POST /api/playground/sessions/{session_id}/integrity/refresh`
  - `GET /api/playground/snapshots/{snapshot_id}/trust-summary?session_id=...`
  - `POST /api/playground/sessions/{session_id}/exports/forensic-bundle`
  - `GET /api/playground/sessions/{session_id}/lineage`
- Enhanced endpoint:
  - `GET /api/playground/sessions/{session_id}/forensic-view`
    now supports `workflow_mode=quick|deep|academic`.
- Extended history payload (additive):
  - `integrity_overview`
  - `session_timeline_integrity`
  - `execution_integrity_rows`
  - `snapshot_trust_rows`

### Database & Migration
- Added migration `002_forensic_integrity_expansion.sql`.
- Added migration `003_forensic_trust_workflow.sql`.
- Extended migration execution strategy in `PlaygroundDB.init_db()` to apply
  all `*.sql` in lexical order with `schema_migrations` tracking.
- Added trust-related session columns:
  - `session_integrity_hash`
  - `session_integrity_status`
  - `session_integrity_verified_at`

### Frontend & UX
- Added Playground trust controls:
  - workflow mode selector,
  - integrity overview action,
  - verify snapshot action,
  - forensic bundle export action,
  - lineage view action.
- Added artifact trust drawer with grouped sections:
  - acquisition metadata
  - integrity metadata
  - transformation metadata
  - provenance metadata
- Added execution-level trust chips in history details:
  - Integrity
  - Snapshot
  - Schema Drift
  - Transform

### Testing & Verification
- Added tests:
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
- Verified regression suite for Playground schema, service flow, history API,
  integrity, trust workflow, and rendering-mode contracts.

## [2026-05-09] Playground Private Docs & Tutorial Isolation

### New Features
- Added `SYSTEM_MAP_PLAYGROUND.md` for private Playground architecture and
  operational notes.
- Added `CHANGELOG_PLAYGROUND.md` as a dedicated Playground-only changelog.
- Added `/playground/tutorial` as a private documentation entrypoint for the
  Playground lab.

### Architecture & Backend
- Added `GET /playground/tutorial` guarded by the strict `Pantronux` admin gate.
- Added `GET /api/playground/tutorial/content` reading
  `playground_runtime/SYSTEM_MAP_PLAYGROUND.md`.
- Preserved the existing main tutorial routes without mixing content sources.

### Frontend & UX
- Added a `Tutorial` button to the Playground banner in the dashboard.
- Introduced a dedicated `playground_tutorial.html` page that mirrors the main
  tutorial renderer but points to the private Playground markdown source.

### Access Control
- Locked the Playground tutorial surface to the same strict access policy as
  Playground runtime: `Pantronux` only.

### Testing & Verification
- Added tutorial route tests for allowed and forbidden access cases.
- Verified the main tutorial route remains unchanged.

## [2026-05-09] Execute Button Loading and Output Actions

### New Features
- Added loading state to the Playground `Execute` button.
- Added `Copy` and `Download` actions to the Playground output panel.

### Frontend & UX
- Disabled `Execute` while a request is in flight to prevent double-submit.
- Updated button label to `Executing...` during active requests.
- Added clipboard copy of raw Playground output.
- Added JSON file download of current Playground output.

### Testing & Verification
- Verified the UI behavior manually in the Playground panel.
- Preserved existing Playground API flow and output rendering.

## [2026-05-09] Gemini Adapter Endpoint Fix

### Fixed
- Corrected Gemini Playground execution to use Google's OpenAI-compatible
  endpoint under `v1beta/openai/chat/completions`.

### Architecture & Backend
- Replaced the broken `/v1/chat/completions` assumption in
  `playground_runtime/providers/adapters/gemini_adapter.py`.

### Testing & Verification
- Added adapter-level regression coverage to ensure the Gemini URL stays
  correct.

## [2026-05-09] Provider Checklist and Comparative Auto-Execution UX

### New Features
- Replaced single-provider dropdown with provider checklist selection.
- Added automatic execution mode switching:
  - one provider -> single execution
  - two or more providers -> comparative execution

### Frontend & UX
- Simplified repeated research across multiple models with one prompt submit.
- Improved Playground output visibility for comparative responses.

### Testing & Verification
- Preserved comparative service-flow tests and provider registry checks.

## [2026-05-09] Schema Normalization Hardening

### New Features
- Hardened mapper-side normalization without changing
  `CanonicalInferenceTrace`.
- Preserved no-hidden-reasoning projection contract.

### Architecture & Backend
- Strengthened reasoning-policy traversal and normalization warnings.
- Kept raw evidence storage separate from canonical projection.

### Testing & Verification
- Extended normalization tests under `tests/test_playground_schema_normalization.py`.

## [2026-05-09] API and UI Mount Milestone

### New Features
- Added isolated Playground API mount under `/api/playground/*`.
- Added Playground mode in the dashboard with session, execution, and quick
  check controls.

### Architecture & Backend
- Mounted Playground router conditionally from `main.py`.
- Enforced feature flags via `KURO_PLAYGROUND_ENABLED` and
  `KURO_PLAYGROUND_API_ENABLED`.
- Preserved one-way host import direction.

### Frontend & UX
- Added `Normal // Playground` runtime toggle.
- Added Playground panel for session creation, execution, and trace listing.

### Access Control
- Restored strict access semantics so only `Pantronux` may operate Playground.

### Testing & Verification
- Added and preserved conditional mount test coverage.

## [2026-05-09] Initial KPR Runtime Implementation

### New Features
- Implemented `PlaygroundRuntimeService` for isolated KPR orchestration.
- Added provider registry, comparative router, normalization registry, forensic
  evidence flow, ontology reconstruction, and report export hooks.

### Architecture & Backend
- Introduced `playground_runtime/config.py` with distinct
  `KURO_PLAYGROUND_*` and `PLAYGROUND_*` namespaces.
- Added `PlaygroundDB` schema and helper layer.
- Implemented canonical six-provider support only:
  `openai`, `gemini`, `anthropic`, `deepseek`, `ollama`, `openai_compat`.
- Intentionally skipped multi-alias `openai_compat` support in this phase.
- Added skeleton `purge_expired_evidence()` in the Playground DB layer.

### Access Control
- Kept Playground safe-by-default with feature flags off unless explicitly
  enabled.

### Testing & Verification
- Added Playground config, DB, provider registry, service flow, API, and
  boundary validator coverage.
