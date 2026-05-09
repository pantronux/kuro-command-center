# CHANGELOG_PLAYGROUND — Kuro Playground Runtime

> Private changelog for the isolated Playground lab under `playground_runtime/`.
> This document is separate from the main `CHANGELOG.md` by design.

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
