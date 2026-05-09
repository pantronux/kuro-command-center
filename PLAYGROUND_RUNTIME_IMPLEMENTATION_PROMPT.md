# Kuro Playground Runtime — Implementation Prompt
**Subsystem Alias:** AI Cognitive Forensics Laboratory (ACFL)
**Target Version:** Kuro AI V1.1.0 Beta 1 "Sovereign Chat" onward
**Prompt Status:** Pre-Implementation Review Gate

---

## ⚠️ MANDATORY PRE-EXECUTION REQUIREMENT

**DO NOT generate any code, migration, or file modification until an explicit approval is received for the Implementation Plan.**

Before producing the Implementation Plan, you MUST:

1. **Read and parse** `SYSTEM_MAP.md` in full — every section, every module entry, every topology note.
2. **Cross-reference** the Clean Tree (`kuro_backend/`, `agency/`, `ingestion_center/`, `execution/`, `services/`, `tools/`) against every proposed Playground module to confirm there are zero naming collisions and zero shared runtime paths.
3. **Identify** all existing feature-flag env vars (e.g. `KURO_ALIGNMENT_THRESHOLD`, `KURO_ADVISOR_AUTO_SEARCH`, `KURO_TRACE_SPAN_TIMEOUT_S`) and ensure no Playground flag clashes with any existing key in `config.py` → `Settings`.
4. **Verify** that the proposed `playground_runtime/` subtree is fully disjoint from:
   - `kuro_backend/langgraph_core.py` (the production LangGraph DAG)
   - `kuro_backend/memory_coordinator.py` (3-layer memory orchestration)
   - `kuro_backend/perpetual_memory.py` (Mem0 + ChromaDB long-term store)
   - `kuro_backend/epistemic_filter.py` (Anti-Halusinasi enforcement)
   - All `*.db` files listed under `kuro_intelligence.db`, `kuro_short_term.db`, `kuro_chat_history.db`

The Implementation Plan MUST evidence this analysis explicitly before any architectural design is presented.

---

## 1. Strategic Context & Architectural Role

You are implementing **Kuro Playground Runtime** (KPR) — a research-grade, isolated subsystem within Kuro AI V1.1.0 Beta 1.

KPR is **not** a chat feature, persona, or extension of the production LangGraph reasoning core. It is a **standalone forensic research environment** that runs in isolated sessions, operates under independent governance, and exposes no shared state with Kuro Core's production memory tiers.

**Dissertation Alignment:**
KPR is the primary technical substrate for dissertation research toward:
> *Generalized Ontological Framework for AI Forensics (GOFAF)*

It must be capable of ingesting heterogeneous AI provider outputs and normalizing them into a unified forensic abstraction (`CanonicalInferenceTrace`) without destroying raw evidence.

**Architectural Position in Kuro V1.1.0:**
- KPR is **parallel** to `kuro_backend/` — not nested inside it
- KPR has **no import dependency** on `langgraph_core.py`, `memory_coordinator.py`, `perpetual_memory.py`, `personas.py`, or any production persona logic
- KPR communicates with the host Kuro process **only** through a thin governance gate and a dedicated SQLite database (`kuro_playground.db`) that is never opened by the production process

---

## 2. Constraints & Invariants

These constraints are **non-negotiable**. The Implementation Plan MUST confirm each one explicitly.

### 2.1 Isolation Invariants

| Constraint | Specification |
|---|---|
| No shared memory | KPR MUST NOT read from or write to Mem0, ChromaDB (`kuro_chromadb/`), `kuro_short_term.db`, or `kuro_chat_history.db` |
| No persona contamination | KPR MUST NOT import or invoke `personas.py`, `build_system_instruction`, or any T1/T2/T3 agency node |
| No production LLM routing | KPR calls providers via its own `ProviderRouter` — never via `langgraph_core.process_chat_with_graph_stream` |
| Dedicated database | All KPR persistence goes to `kuro_playground.db` exclusively |
| No Arize Phoenix contamination | KPR telemetry MUST use a separate OTel project name (`kuro-playground`) distinct from the production `kuro-ai` project in `observability.py` |

### 2.2 Feature Flag Invariants

- ALL KPR capabilities MUST be gated behind feature flags
- Default state for ALL flags: `OFF` (`False`)
- Flag namespace: `KURO_PLAYGROUND_*`
- Flags are read from `.env` via `config.py` → `PlaygroundSettings` (a separate Pydantic `BaseSettings` subclass, not merged into the existing `Settings` class)
- No KPR flag may share a key prefix with any existing Kuro flag

### 2.3 Raw Evidence Invariants

- Provider raw JSON responses MUST be stored verbatim before any normalization step
- Normalization pipelines MUST operate on **copies**, never mutate the stored raw artifact
- Every stored artifact MUST carry: `provider_id`, `model_version`, `response_schema_version`, `request_id`, `prompt_sha256`, `dataset_version`, `collected_at_utc`
- Destruction of raw evidence at any normalization stage is a **critical defect**

### 2.4 Reasoning Trace Invariants

- KPR MUST NOT attempt to extract, simulate, reconstruct, or approximate hidden chain-of-thought from any provider
- Only **provider-visible** metadata is permissible: token counts, finish reasons, grounding chunks, citation objects, safety ratings, latency metrics
- Any implementation path that could produce fabricated reasoning traces MUST be rejected at design review

---

## 3. Implementation Plan Requirements

The output of this prompt is a **complete Implementation Plan document** — not code. The plan MUST contain all sections below, in the order listed. Each section must be substantive; placeholder headings are not acceptable.

---

### Section 1 — Strategic Overview

Write a precise technical statement covering:

- What KPR is, stated as a formal system definition (not marketing language)
- Its architectural role relative to `kuro_backend/`, `main.py`, and the LangGraph DAG
- How it differs from Kuro Core at the runtime, memory, and governance levels
- Its dissertation alignment: which GOFAF research questions it addresses
- Which existing Kuro subsystems it touches (read-only, write-only, or none) and under what conditions

---

### Section 2 — System Architecture

Describe the full subsystem topology:

**2.1 Runtime Boundary Diagram**
Produce a Mermaid diagram showing:
- KPR subsystem boundary (dashed border)
- All entry points into KPR (API routes, CLI, SDK)
- All exit points from KPR (DB writes, export artifacts, telemetry)
- Explicit "NO CROSSING" edges to: `langgraph_core`, `memory_coordinator`, `perpetual_memory`, `personas`, all production `*.db` files
- The governance gate between KPR and Kuro Core

**2.2 Data Flow Specification**
For each of the following flows, describe: trigger → processing stages → persistence targets → telemetry events:
- Provider invocation flow
- Raw evidence preservation flow
- Schema normalization flow (`CanonicalInferenceTrace` construction)
- Ontology reconstruction flow
- Forensic report generation flow

**2.3 Governance Gate Design**
Specify exactly:
- How the governance gate blocks KPR from writing to production memory
- What signals the gate produces when a boundary violation is attempted
- Whether the gate is enforced at the Python import level, runtime level, or both

---

### Section 3 — Clean Tree Structure

Produce the **complete proposed file tree** for `playground_runtime/`. Every directory and file must be listed. For each file, provide a one-line purpose annotation matching the Kuro Header Doc contract:

```
playground_runtime/
├── __init__.py                    # [purpose]
├── config.py                      # PlaygroundSettings: Pydantic BaseSettings, KURO_PLAYGROUND_* flags
├── governance/
│   ├── __init__.py
│   ├── isolation_gate.py          # [purpose]
│   └── boundary_validator.py      # [purpose]
├── providers/
│   ├── __init__.py
│   ├── registry.py                # [purpose]
│   ├── capability_registry.py     # [purpose]
│   ├── health_monitor.py          # [purpose]
│   ├── router.py                  # [purpose]
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base_adapter.py        # [purpose]
│   │   ├── gemini_adapter.py      # [purpose]
│   │   ├── openai_adapter.py      # [purpose]
│   │   ├── anthropic_adapter.py   # [purpose]
│   │   ├── deepseek_adapter.py    # [purpose]
│   │   ├── ollama_adapter.py      # [purpose]
│   │   └── openai_compat_adapter.py  # [purpose]
│   └── schemas/
│       ├── provider_manifest.py   # [purpose]
│       └── capability_spec.py     # [purpose]
├── schema/
│   ├── __init__.py
│   ├── canonical_trace.py         # CanonicalInferenceTrace dataclass
│   ├── evidence_artifact.py       # [purpose]
│   ├── normalization_registry.py  # [purpose]
│   └── mappers/
│       ├── __init__.py
│       ├── base_mapper.py         # [purpose]
│       ├── gemini_mapper.py       # [purpose]
│       ├── openai_mapper.py       # [purpose]
│       ├── anthropic_mapper.py    # [purpose]
│       └── deepseek_mapper.py     # [purpose]
├── telemetry/
│   ├── __init__.py
│   ├── collector.py               # [purpose]
│   ├── otel_bridge.py             # [purpose — separate project: kuro-playground]
│   └── event_schema.py            # [purpose]
├── forensic/
│   ├── __init__.py
│   ├── evidence_store.py          # [purpose]
│   ├── trace_indexer.py           # [purpose]
│   ├── hallucination_analyzer.py  # [purpose]
│   └── epistemic_diff.py          # [purpose]
├── ontology/
│   ├── __init__.py
│   ├── reconstructor.py           # [purpose]
│   ├── concept_graph.py           # [purpose]
│   ├── alignment_scorer.py        # [purpose]
│   └── graph_exporter.py          # RDF-star + JSON-LD export
├── evaluation/
│   ├── __init__.py
│   ├── evaluator.py               # [purpose]
│   ├── metrics/
│   │   ├── hallucination_metric.py
│   │   ├── grounding_metric.py
│   │   ├── citation_integrity_metric.py
│   │   ├── epistemic_divergence_metric.py
│   │   └── ontology_consistency_metric.py
│   └── report_builder.py          # [purpose]
├── modes/
│   ├── __init__.py
│   ├── base_mode.py               # [purpose]
│   ├── research_mode.py           # [purpose]
│   ├── forensic_mode.py           # [purpose]
│   ├── comparative_mode.py        # [purpose]
│   └── ontology_mode.py           # [purpose]
├── db/
│   ├── __init__.py
│   ├── playground_db.py           # kuro_playground.db schema bootstrap + CRUD
│   └── migrations/
│       └── 001_initial_schema.sql # [purpose]
├── export/
│   ├── __init__.py
│   ├── report_exporter.py         # [purpose]
│   └── formats/
│       ├── json_exporter.py
│       ├── rdf_exporter.py
│       └── csv_exporter.py
└── api/
    ├── __init__.py
    ├── router.py                  # FastAPI router — mounted ONLY when KURO_PLAYGROUND_API_ENABLED=true
    └── schemas.py                 # Request/response Pydantic models
```

Fill in all `[purpose]` annotations. If additional files are needed beyond this template, add them with justification.

---

### Section 4 — Kuro Core Integration Points (Strictly Bounded)

Specify, with module-level precision:

**4.1 What KPR Reuses (Read-Only)**
- Which `config.py` settings (if any) KPR reads without modification
- Whether `observability.py` bootstrap is reused or KPR initializes its own OTel exporter
- Whether KPR's FastAPI router is mounted into `main.py` or runs as a separate process/port

**4.2 What KPR Does Not Touch**
Enumerate explicitly: every module in `kuro_backend/` that KPR MUST NEVER import, and why.

**4.3 Feature Flag Integration**
- Define `PlaygroundSettings` as a Pydantic `BaseSettings` subclass in `playground_runtime/config.py`
- `PlaygroundSettings` MUST handle **two key namespaces** independently:
  - Provider credentials: `PLAYGROUND_OPENAI_API_KEY`, `PLAYGROUND_OPENAI_MODEL_NAME`, `PLAYGROUND_GEMINI_API_KEY`, `PLAYGROUND_GEMINI_MODEL_NAME`, etc. — flat `PLAYGROUND_` prefix, no `KURO_`
  - Runtime flags: `KURO_PLAYGROUND_ENABLED`, `KURO_PLAYGROUND_API_ENABLED`, etc. — `KURO_PLAYGROUND_` prefix
- These namespaces MUST NOT be merged — the split is intentional and matches the actual `.env` layout
- List all flags with: name, type, default, effect, activation stage
- Show how `main.py` mounts the KPR router conditionally on `KURO_PLAYGROUND_API_ENABLED`

**4.4 Runtime Isolation Mechanism**
Describe the Python-level enforcement strategy that prevents accidental cross-imports between `playground_runtime/` and `kuro_backend/`. Options: import guards, separate subprocess, namespace isolation, or runtime boundary validator.

---

### Section 5 — Database Schema: `kuro_playground.db`

Design the complete SQLite schema for `kuro_playground.db`. This database is **never opened by the production Kuro process**.

For each table, provide:
- Full `CREATE TABLE` DDL with types, constraints, and default values
- Index strategy with justification for each index
- Foreign key relationships
- Retention policy (if applicable)
- Notes on raw evidence preservation

Required tables (minimum — add more if architecturally necessary):

| Table | Primary Purpose |
|---|---|
| `playground_sessions` | Session lifecycle, mode, runtime config snapshot |
| `model_executions` | Per-execution record: provider, model, latency, token usage, finish reason |
| `raw_evidence` | Verbatim provider JSON + metadata; never mutated post-insert |
| `canonical_traces` | Normalized `CanonicalInferenceTrace` records linked to `raw_evidence` |
| `telemetry_events` | OTel-compatible event log per execution |
| `hallucination_records` | Detected hallucination instances with evidence provenance |
| `epistemic_diffs` | Divergence records between two or more model executions on identical prompts |
| `ontology_mappings` | Extracted concept nodes and edges per trace |
| `ontology_graphs` | Aggregated graph snapshots per session |
| `forensic_reports` | Report generation metadata + export artifact references |
| `provider_metadata` | Provider registry state: version, endpoint, capability hash |
| `runtime_configs` | Serialized runtime config per session for reproducibility |
| `reproducibility_records` | Prompt hash, dataset version, seed, execution fingerprint |
| `feature_flag_snapshots` | Snapshot of all `KURO_PLAYGROUND_*` flags at session start |

For each table, include: insert path, query paths, retention behavior, and raw evidence immutability guarantees.

---

### Section 6 — Dynamic Schema Normalization Design

Design the `CanonicalInferenceTrace` schema and the normalization pipeline.

**6.1 CanonicalInferenceTrace Specification**
Define as a Python dataclass or Pydantic model. Fields must include (minimum):

```python
@dataclass
class CanonicalInferenceTrace:
    trace_id: str                    # UUID v4
    session_id: str
    execution_id: str
    provider_id: str                 # Registry key, not hardcoded
    model_id: str
    model_version: str
    schema_version: str              # Mapper version for backward compat
    prompt_sha256: str               # SHA-256 of normalized prompt
    dataset_version: Optional[str]
    collected_at_utc: datetime
    response_text: Optional[str]
    finish_reason: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    latency_ms: Optional[float]
    grounding_chunks: List[dict]     # Provider-sourced only, never fabricated
    citation_objects: List[dict]
    safety_ratings: Optional[dict]
    provider_raw_id: str             # FK → raw_evidence.id
    forensic_flags: List[str]        # e.g. ["GROUNDING_ABSENT", "FINISH_REASON_ABNORMAL"]
    normalization_warnings: List[str]
```

**6.2 Provider Mapper Interface**
Define the `BaseMapper` abstract interface that all provider mappers implement. Include: method signatures, contract guarantees, and error handling strategy for unknown fields.

**6.3 Schema Evolution Strategy**
Explain how the normalization pipeline handles:
- New fields added by a provider in a future API version
- Fields renamed or removed by a provider
- Schema version mismatches between stored `raw_evidence` and current mapper version

**6.4 Backward Compatibility Guarantee**
Define the backward compatibility contract: when a stored `raw_evidence` record is re-normalized using a newer mapper version, what guarantees hold about the resulting `CanonicalInferenceTrace`?

---

### Section 7 — Multi-Model Provider Runtime

Design the complete provider registry architecture.

**7.1 Provider Registry**
Define `ProviderRegistry` — a runtime-loadable registry that:
- Reads provider configs from `.env` (no code changes required to add a provider)
- Supports: `gemini`, `openai`, `claude`, `deepseek`, `ollama`, any `openai_compat_*` endpoint
- Exposes: `register()`, `get()`, `list_active()`, `health_check()`, `get_capability_spec()`

**7.2 Capability Registry**
Define `CapabilitySpec` — a per-provider capability declaration covering:
- Supported modalities (text, image, code, structured output)
- Grounding support (yes/no, type)
- Citation support (yes/no, format)
- Streaming support
- Tool use / function calling support
- Max context window
- Whether provider exposes reasoning traces (yes/no — KPR never tries to extract hidden ones)

**7.3 Dynamic Provider Discovery**
Specify the `.env` convention for registering providers without code changes.

The Playground uses a **flat `PLAYGROUND_` prefix** convention — distinct from all Kuro Core keys (which use `KURO_`). This namespace is reserved exclusively for KPR and MUST NOT overlap with any key in `config.py` → `Settings`.

Actual `.env` key pattern (canonical reference):

```env
# ── OpenAI Provider ──────────────────────────────────────────
PLAYGROUND_OPENAI_API_KEY=sk-...
PLAYGROUND_OPENAI_MODEL_NAME=gpt-4o

# ── Gemini Provider ──────────────────────────────────────────
PLAYGROUND_GEMINI_API_KEY=AI...
PLAYGROUND_GEMINI_MODEL_NAME=gemini-2.0-flash

# ── Anthropic / Claude Provider ──────────────────────────────
PLAYGROUND_ANTHROPIC_API_KEY=sk-ant-...
PLAYGROUND_ANTHROPIC_MODEL_NAME=claude-sonnet-4-20250514

# ── DeepSeek Provider ────────────────────────────────────────
PLAYGROUND_DEEPSEEK_API_KEY=...
PLAYGROUND_DEEPSEEK_MODEL_NAME=deepseek-chat

# ── Ollama (local, no API key required) ──────────────────────
PLAYGROUND_OLLAMA_BASE_URL=http://localhost:11434
PLAYGROUND_OLLAMA_MODEL_NAME=llama3.1:8b

# ── Generic OpenAI-Compatible Endpoint ───────────────────────
PLAYGROUND_OPENAI_COMPAT_BASE_URL=http://localhost:8080/v1
PLAYGROUND_OPENAI_COMPAT_API_KEY=optional-token
PLAYGROUND_OPENAI_COMPAT_MODEL_NAME=local-model
```

**Provider activation rule:** A provider is considered **active** by `ProviderRegistry` if and only if its corresponding `PLAYGROUND_<PROVIDER>_API_KEY` (or `BASE_URL` for keyless providers like Ollama) is present and non-empty in `.env`. No boolean toggle flag is required — key presence is the activation signal.

`PlaygroundSettings` MUST load these via Pydantic `BaseSettings` with `env_prefix=""` (no global prefix, since each key already carries its own `PLAYGROUND_` namespace). The registry MUST iterate over all known provider slots at startup and mark each as `active` or `inactive` based on key presence — logging inactive providers at `DEBUG` level without raising errors.

**7.4 Provider Health Management**
Define the health check cycle: interval, failure threshold, circuit breaker behavior, and degradation mode when a provider is unavailable mid-session.

**7.5 OpenAI-Compatible Adapter**
Specify the `openai_compat_adapter.py` contract: what it requires from a provider endpoint (minimum API surface), and how it maps to `CanonicalInferenceTrace`.

---

### Section 8 — Playground Runtime Modes

Define each mode as a distinct runtime configuration profile. Each mode MUST specify:

| Parameter | Description |
|---|---|
| `memory_policy` | How session state is handled: ephemeral / session-scoped / none |
| `grounding_strictness` | Whether ungrounded claims are flagged, blocked, or logged |
| `hallucination_tolerance` | Detection threshold and response policy |
| `reproducibility_level` | Seed locking, config snapshotting, prompt hashing |
| `telemetry_policy` | What events are emitted and at what granularity |
| `multi_provider_allowed` | Whether cross-provider comparison is enabled in this mode |
| `raw_evidence_retention` | Retention window for raw JSON artifacts |
| `export_formats_allowed` | Which export formats are available |

**Mode 1: Research Mode**
General-purpose exploration. Relaxed grounding strictness. Hallucination flagging ON but non-blocking. Full telemetry.

**Mode 2: Strict Forensic Mode**
Dissertation-grade evidence collection. Maximum reproducibility. All provider responses stored verbatim. Grounding strictness: HIGH. Hallucination tolerance: ZERO (blocks response if detected; logs as `FORENSIC_HOLD`). Telemetry: maximum granularity.

**Mode 3: Comparative Mode**
Identical prompts dispatched to N providers simultaneously. Results stored as a `comparison_set` keyed by `prompt_sha256`. Epistemic diff computed automatically post-execution. Requires N ≥ 2 active providers.

**Mode 4: Ontology Mapping Mode**
Focused on concept extraction, entity resolution, and ontology reconstruction from provider outputs. Activates `ontology/reconstructor.py`. Exports ontology graphs as RDF-star or JSON-LD. Does not require grounding.

---

### Section 9 — Flow Diagrams (Mermaid)

Produce detailed Mermaid flow diagrams for each of the following. Each diagram must show: actors, decision points, error paths, and persistence targets.

**Diagram A: Dual-Provider Execution Flow**
Show: session init → prompt ingestion → parallel provider dispatch → raw evidence storage → normalization → CanonicalInferenceTrace persistence → telemetry emission → comparison_set construction

**Diagram B: Dynamic Schema Normalization Flow**
Show: raw_evidence retrieval → provider_id resolution → mapper selection → field mapping → normalization_warnings accumulation → CanonicalInferenceTrace construction → schema_version tagging → DB persistence

**Diagram C: Telemetry Collection Flow**
Show: execution trigger → OTel span creation (project: `kuro-playground`) → event emission at each pipeline stage → span close → export to Phoenix (separate project namespace) → telemetry_events table write

**Diagram D: Ontology Reconstruction Flow**
Show: CanonicalInferenceTrace input → concept extraction → entity resolution → edge inference → concept_graph construction → alignment scoring → graph_exporter → RDF-star / JSON-LD output

**Diagram E: Comparative Epistemic Analysis Flow**
Show: comparison_set input (N traces) → pairwise epistemic_diff computation → divergence scoring → hallucination cross-reference → epistemic_diff table persistence → report_builder trigger

**Diagram F: Forensic Report Generation Flow**
Show: session_id input → data aggregation (executions, traces, diffs, ontology) → report_builder assembly → reproducibility_record attachment → format selection → export artifact generation → forensic_reports table update

---

### Section 10 — Evaluation Framework

Design the evaluation methodology for KPR research sessions.

**10.1 Evaluation Dimensions**

For each dimension, specify: metric definition, measurement method, scoring range, evidence sources, and failure thresholds.

| Dimension | Definition |
|---|---|
| Hallucination Rate | Ratio of factual claims without grounding evidence to total factual claims |
| Grounding Coverage | Ratio of claims with provider-sourced grounding chunks to total claims |
| Citation Integrity | Accuracy and completeness of provider-returned citations |
| Forensic Completeness | Completeness of `CanonicalInferenceTrace` fields for a given provider |
| Ontology Consistency | Cross-session stability of extracted concept nodes for identical prompts |
| Epistemic Divergence | KL-divergence proxy or semantic distance between two providers' responses to identical prompts |

**10.2 Evaluation Runtime**
Describe how evaluations are triggered (manual, automatic post-execution, scheduled), stored, and surfaced. Evaluations MUST reference `execution_id` and `trace_id` for evidence traceability.

**10.3 Comparison Validity Rules**
Define the conditions under which a multi-provider comparison is considered statistically valid for dissertation citation: minimum N providers, prompt normalization requirements, dataset version pinning, seed locking.

---

### Section 11 — Exportable Research Report

Define the forensic report format and export pipeline.

**11.1 Report Schema**
The forensic report MUST contain (minimum):
- Session metadata: `session_id`, `mode`, `created_at`, `runtime_config_hash`
- Provider manifest: all providers active during session, their `model_version` and `capability_spec_hash`
- Execution summary: per-execution latency, token usage, finish reason, forensic flags
- Canonical trace index: links to all `CanonicalInferenceTrace` records
- Epistemic diff summary: divergence scores, hallucination cross-references
- Ontology graph: embedded or linked (RDF-star / JSON-LD)
- Reproducibility record: `prompt_sha256`, `dataset_version`, `feature_flag_snapshot_id`
- Evidence integrity: SHA-256 of all `raw_evidence` records in session

**11.2 Export Pipeline**
Show the pipeline from `forensic_reports` table → `report_builder.py` → format renderers. Supported formats: `json`, `rdf`, `csv`. (Note: do not reuse `kuro_backend/export_engine/` — KPR has its own `export/` package.)

**11.3 Reproducibility Guarantee**
Define what it means for a KPR session to be fully reproducible, and what metadata a researcher must publish alongside a dissertation citation to allow independent replication.

---

### Section 12 — Governance & Safety Design

**12.1 Runtime Isolation Architecture**
Describe the enforcement layers (in order of precedence):
1. Python import isolation: `playground_runtime/` MUST NOT import from `kuro_backend/`
2. Database isolation: `kuro_playground.db` is never opened by the production process
3. OTel isolation: separate project name `kuro-playground`
4. Feature flag gate: all KPR API routes return `403 Disabled` when `KURO_PLAYGROUND_API_ENABLED=false`

**12.2 Memory Boundary Enforcement**
Specify the runtime checks in `governance/isolation_gate.py` that:
- Verify no KPR session object holds a reference to any Mem0 client, ChromaDB collection, or production `*.db` connection
- Log a `BOUNDARY_VIOLATION` event if a violation is detected
- Raise `PlaygroundIsolationError` (a KPR-specific exception, not inheriting from any Kuro Core exception class)

**12.3 Provider Sandboxing**
Specify what information KPR provider adapters are permitted to receive:
- Playground prompt text
- `CanonicalInferenceTrace` schema (for response mapping)
- Provider API keys from `PlaygroundSettings`
- **NOT**: any Kuro Core memory content, persona instructions, user PII from production sessions

**12.4 No Hidden Reasoning Exposure**
Specify the static analysis or runtime check that enforces Rule 7 (no chain-of-thought extraction). This must be more than a comment — it must be an enforceable contract.

---

### Section 13 — Feature Flags Strategy

> **⚠️ `.env` Key Namespace Split — IMPORTANT**
>
> KPR uses **two distinct key namespaces** in `.env`, each with a different purpose:
>
> | Namespace | Purpose | Loaded by |
> |---|---|---|
> | `PLAYGROUND_*` | Provider credentials & model names (e.g. `PLAYGROUND_OPENAI_API_KEY`) | `PlaygroundSettings.providers` block |
> | `KURO_PLAYGROUND_*` | Runtime behavior flags (e.g. `KURO_PLAYGROUND_ENABLED`) | `PlaygroundSettings.flags` block |
>
> `PLAYGROUND_*` keys MUST NOT be prefixed with `KURO_` — they follow the flat convention visible in the actual `.env` (see Section 7.3).
> `KURO_PLAYGROUND_*` keys MUST NOT clash with any existing Kuro Core key in `config.py` → `Settings`.

**13.1 Complete Flag Registry**

| Flag (`KURO_PLAYGROUND_*`) | Type | Default | Effect | Activation Stage |
|---|---|---|---|---|
| `KURO_PLAYGROUND_ENABLED` | `bool` | `False` | Master switch — enables the entire subsystem | Phase 1 |
| `KURO_PLAYGROUND_API_ENABLED` | `bool` | `False` | Mounts KPR FastAPI router into `main.py` | Phase 1 |
| `KURO_PLAYGROUND_RESEARCH_MODE` | `bool` | `False` | Activates Research Mode session type | Phase 1 |
| `KURO_PLAYGROUND_FORENSIC_MODE` | `bool` | `False` | Activates Strict Forensic Mode | Phase 2 |
| `KURO_PLAYGROUND_COMPARATIVE_MODE` | `bool` | `False` | Activates Comparative Mode (requires N≥2 active providers) | Phase 2 |
| `KURO_PLAYGROUND_ONTOLOGY_MODE` | `bool` | `False` | Activates Ontology Mapping Mode | Phase 4 |
| `KURO_PLAYGROUND_TELEMETRY_ENABLED` | `bool` | `False` | Enables OTel emission under `kuro-playground` project | Phase 3 |
| `KURO_PLAYGROUND_HALLUCINATION_ANALYZER` | `bool` | `False` | Enables hallucination detection pipeline | Phase 3 |
| `KURO_PLAYGROUND_EPISTEMIC_DIFF` | `bool` | `False` | Enables epistemic divergence computation | Phase 5 |
| `KURO_PLAYGROUND_ONTOLOGY_RECONSTRUCTION` | `bool` | `False` | Enables ontology reconstructor + graph exporter | Phase 4 |
| `KURO_PLAYGROUND_REPORT_EXPORT` | `bool` | `False` | Enables forensic report generation and export | Phase 6 |
| `KURO_PLAYGROUND_MAX_CONCURRENT_PROVIDERS` | `int` | `2` | Maximum simultaneous provider calls in Comparative Mode | Phase 2 |
| `KURO_PLAYGROUND_RAW_EVIDENCE_RETENTION_DAYS` | `int` | `90` | Retention window for `raw_evidence` records | Phase 1 |

**13.2 Activation Stage Definitions**
Map each Phase (1–6) to a set of flags that MUST be active. Flags from later phases MUST NOT be activated unless all earlier-phase flags for that feature chain are also active.

**13.3 Rollback Strategy**
Define the rollback procedure for each activation stage: which flags to flip, whether a DB migration rollback is required, and how to verify post-rollback that Kuro Core is unaffected.

---

### Section 14 — Phased Implementation Roadmap

For each phase, specify: deliverables, acceptance criteria, integration test requirements, and flag states.

**Phase 1 — Core Playground Runtime**
Deliverables: `playground_runtime/` directory skeleton, `PlaygroundSettings`, `playground_db.py` with schema bootstrap, `governance/isolation_gate.py`, `governance/boundary_validator.py`, KPR FastAPI router (stub endpoints), `raw_evidence` table, `playground_sessions` table.
Acceptance criteria: KPR module loads without importing any `kuro_backend/` symbol. `kuro_playground.db` created independently. All Phase 1 flags default OFF.

**Phase 2 — Multi-Provider Orchestration**
Deliverables: `providers/registry.py`, all provider adapters (gemini, openai, anthropic, deepseek, ollama, openai_compat), `CanonicalInferenceTrace` dataclass, `schema/mappers/`, Comparative Mode, `model_executions` table, `canonical_traces` table.
Acceptance criteria: Two providers dispatch identical prompts. Both raw responses stored verbatim. Both normalized to `CanonicalInferenceTrace`. No production memory touched.

**Phase 3 — Forensic Telemetry**
Deliverables: `telemetry/collector.py`, `telemetry/otel_bridge.py` (project: `kuro-playground`), `telemetry_events` table, hallucination analyzer (initial heuristic implementation), `hallucination_records` table.
Acceptance criteria: OTel spans visible in Phoenix under `kuro-playground` project only. Hallucination events persisted with evidence FK.

**Phase 4 — Ontology Reconstruction**
Deliverables: `ontology/reconstructor.py`, `ontology/concept_graph.py`, `ontology/alignment_scorer.py`, `ontology/graph_exporter.py` (RDF-star + JSON-LD), `ontology_mappings` table, `ontology_graphs` table, Ontology Mapping Mode.
Acceptance criteria: Concept graph generated from two providers' responses on identical prompt. Graph exported as valid JSON-LD.

**Phase 5 — Comparative Cognition Analysis**
Deliverables: `forensic/epistemic_diff.py`, `evaluation/metrics/epistemic_divergence_metric.py`, `epistemic_diffs` table, full Comparative Mode with automated diff trigger.
Acceptance criteria: Epistemic diff score computed for a 2-provider comparison set. Divergence persisted with trace FKs.

**Phase 6 — Advanced Forensic Evaluation & Reporting**
Deliverables: `evaluation/evaluator.py`, all remaining metrics, `evaluation/report_builder.py`, `export/report_exporter.py`, `forensic_reports` table, `reproducibility_records` table, Strict Forensic Mode.
Acceptance criteria: Full forensic report generated for a Strict Forensic Mode session. Report includes reproducibility record. All raw evidence SHA-256 hashes verified.

---

### Section 15 — Final Architectural Assessment

Write a structured assessment covering:

**15.1 Expected Impact on Kuro V1.1.0**
Quantify the expected impact on: startup time, memory footprint, production LangGraph latency, and production DB contention. Impact should be near-zero for Phases 1–2 when all flags are OFF.

**15.2 Architectural Risks**
Enumerate at minimum: dependency drift between KPR provider adapters and upstream API changes; `kuro_playground.db` growth unbounded by production monitoring; OTel project namespace collision risk; import boundary erosion over time.

**15.3 Forensic Value for Dissertation**
Map each KPR capability to a specific GOFAF research question. Identify which Phase delivers the minimum viable research substrate for dissertation data collection.

**15.4 Scalability Considerations**
Address: what happens when `raw_evidence` volume exceeds SQLite practical limits; whether a future migration to PostgreSQL is feasible without breaking the `CanonicalInferenceTrace` contract; and how the provider registry handles provider API deprecations.

**15.5 Enterprise & Reproducibility Implications**
If KPR is eventually published as part of a dissertation artifact, what additional hardening (auth, audit trail, data sanitization) is required? Which parts of the current design are already enterprise-ready?

---

## 4. Output Format Requirements

The Implementation Plan MUST be delivered as:
- A single structured Markdown document
- All Mermaid diagrams embedded inline (not linked)
- All SQL DDL rendered in fenced code blocks with `sql` syntax tag
- All Python type definitions rendered in fenced code blocks with `python` syntax tag
- Section numbering matching the structure above exactly
- No placeholder text, no "TBD", no deferred sections

**Total expected length:** 4,000–8,000 words minimum. Sections 5 (DB Schema) and 9 (Flow Diagrams) are expected to be the longest.

---

## 5. What Comes After the Plan

Once the Implementation Plan is approved (explicit approval signal required), the following will be executed **in strict phase order**:

1. Phase 1 scaffolding — file tree creation, `PlaygroundSettings`, isolation gate, DB bootstrap
2. Phase 1 integration tests — boundary validator tests, DB isolation tests, flag default tests
3. Header Doc block added to every new file before Phase 2 begins
4. Each subsequent phase follows the same pattern: implement → test → Header Doc → approve → next phase

No phase may begin without passing the acceptance criteria of the previous phase.

---

*Prompt version: 2.0 — Kuro AI V1.1.0 context-aware. Supersedes original v1.0 prompt.*
*Last updated: aligned to SYSTEM_MAP.md V1.1.0 Beta 1 "Sovereign Chat"*
