# Kuro AI — Implementation Plan
## V1.0.0 Beta 7 Proposal — "Sovereign Grounding"

Based on analysis of:
- `SYSTEM_MAP.md`
- `CHANGELOG.md`
- `langgraph_core.py`
- `personas.py`
- `epistemic_filter.py`
- `core.py`
- `llm_utils.py`
- `memory_coordinator.py`
- `memory_manager.py`
- `perpetual_memory.py`

Primary Objectives:
1. Eliminate epistemic label leakage from user-visible responses.
2. Strengthen anti-hallucination pipeline without degrading conversational naturalness.
3. Refactor persona architecture to become more adaptive, expressive, and context-aware.
4. Improve grounding reliability across memory retrieval, AutoRAG, and long-term context.
5. Harden separation between internal reasoning metadata and public-facing response rendering.
6. Reduce rigid/systemic “AI-like” tone while preserving governance and QA discipline.

---

# 1. Executive Diagnosis

## Current Strengths

Kuro already has several strong anti-hallucination primitives:

- Tiered memory architecture.
- AutoRAG fallback loop.
- Retrieval grading.
- Long-term semantic memory.
- Domain-aware epistemic relaxation.
- Structured persona instructions.
- LangGraph orchestration.
- Post-generation epistemic enforcement.
- Multi-agent reasoning structure.

The architecture is already significantly above average for sovereign-agent systems.

---

## Current Critical Weaknesses

### A. Epistemic Label Leakage (HIGH PRIORITY)

Current implementation directly injects:

- `[VERIFIED: memory]`
- `[VERIFIED: search]`
- `[INFERRED]`
- `[SPECULATIVE]`
- `[UNKNOWN]`

into final user-visible response streams.

This creates:

- Internal policy leakage.
- Meta-system exposure.
- Reduced immersion.
- Cognitive clutter.
- Prompt reverse-engineering risk.
- Reduced perceived intelligence quality.

Most critically:

The epistemic enforcement layer currently mixes:

- Internal machine-readable provenance
WITH
- Public natural-language rendering.

This is an architectural separation violation.

---

### B. Persona Rigidity

Current personas are:

- Extremely instruction-heavy.
- Operationally powerful.
- But emotionally/static in delivery.

Symptoms:

- Over-formalized outputs.
- Excessive protocol exposition.
- Mechanical transitions.
- Predictable sentence cadence.
- Persona outputs feel “system prompt shaped.”

Root cause:

Personas currently encode:

- Behavioral policy
- Cognitive protocol
- Tone
- Domain authority
- Safety constraints

inside one giant monolithic prompt.

This prevents:

- Adaptive response style.
- Contextual tone shifting.
- Natural conversational fluidity.
- Lightweight interaction modes.

---

### C. Weak Internal/Public Separation

The following systems are overly coupled:

- Epistemic labels.
- Retrieval grading.
- Audit metadata.
- Tool provenance.
- Internal confidence tracking.

These should NEVER directly flow into user-visible text.

Instead:

Internal metadata should exist in:

- structured state
- hidden telemetry
- DB audit logs
- tracing spans
- response decorators

NOT in natural-language output.

---

### D. Retrieval Confidence Still Too Binary

Current retrieval grading:

- relevant
- ambiguous
- irrelevant

is insufficient for nuanced grounding.

Missing:

- confidence scoring
- evidence density
- contradiction scoring
- temporal freshness
- retrieval source quality weighting

---

### E. Memory Cross-Pollination Risk

Although multi-user isolation already exists, there are still soft risks:

- persona memory bleed
- retrieval over-expansion
- weak namespace fencing
- stale semantic injection
- hallucinated continuity

Especially through:

- Mem0 semantic retrieval
- referent grounding
- context fanout
- auto summarization

---

# 2. Proposed Architecture Direction

## Core Philosophy Shift

Current philosophy:

"Expose provenance visibly."

New philosophy:

"Internally enforce provenance while externally preserving natural intelligence."

Meaning:

The user should FEEL:

- precision
- groundedness
- uncertainty honesty
- contextual awareness

WITHOUT seeing internal implementation labels.

---

# 3. High-Level Refactor Scope

## Systems Affected

### Core Runtime
- `langgraph_core.py`
- `core.py`

### Intelligence Layer
- `epistemic_filter.py`
- `memory_coordinator.py`
- `memory_manager.py`
- `perpetual_memory.py`

### Persona Layer
- `personas.py`

### Generation Utilities
- `llm_utils.py`

### Database
- `kuro_intelligence.db`
- `kuro_short_term.db`

### Observability
- OpenTelemetry spans
- Phoenix traces
- epistemic audit logs

---

# 4. Proposed New Architecture

# Intelligence Engine — Core Refactor

## NEW ARCHITECTURE

```text
User Input
    ↓
Intent Classification
    ↓
Retrieval Orchestration
    ↓
Evidence Fusion Engine
    ↓
Confidence Scoring Engine
    ↓
LLM Generation
    ↓
Internal Epistemic Annotation
    ↓
Natural Language Sanitizer
    ↓
Response Style Harmonizer
    ↓
User Output
```

---

# 5. Epistemic Layer Refactor

## Current Problem

Current system modifies the visible response directly.

Example:

```text
[VERIFIED: memory] You uploaded SYSTEM_MAP.md
```

This should NEVER happen.

---

# NEW DESIGN

## Internal Epistemic Object Model

Instead of text labels:

```python
EpistemicClaim(
    text="SYSTEM_MAP.md uploaded",
    source="memory",
    confidence=0.93,
    visibility="internal"
)
```

---

# New Modules

## NEW FILE

```text
kuro_backend/intelligence/
```

### Structure

```text
kuro_backend/intelligence/
├── epistemic_engine.py
├── confidence_engine.py
├── provenance_tracker.py
├── response_sanitizer.py
├── grounding_validator.py
├── contradiction_detector.py
├── retrieval_quality.py
└── uncertainty_renderer.py
```

---

# 6. Mandatory Anti-Leak Refactor

## NEW MODULE

### `response_sanitizer.py`

Purpose:

Hard-strip ALL internal labels before user rendering.

---

## Functions

### `strip_internal_labels(text)`

Removes:

- `[VERIFIED:*]`
- `[INFERRED]`
- `[SPECULATIVE]`
- `[UNKNOWN]`
- internal confidence tags
- hidden telemetry markers

---

### `normalize_uncertainty_language(text)`

Transforms:

```text
[SPECULATIVE] This may indicate...
```

into:

```text
This could indicate...
```

Natural uncertainty.

No system leakage.

---

### `sanitize_chain_of_thought(text)`

Removes:

- internal reasoning artifacts
- hidden planner traces
- prompt remnants
- retrieval metadata

---

### `validate_user_safe_output(text)`

Final hard-gate before SSE stream.

Rejects output containing:

- hidden labels
- policy blocks
- raw JSON telemetry
- internal DB references
- internal state objects

---

# 7. Epistemic Engine Refactor

## REPLACE

Current:

```text
epistemic_filter.py
```

with:

```text
epistemic_engine.py
```

---

## New Internal Claim Model

```python
@dataclass
class Claim:
    text: str
    source_type: str
    confidence: float
    evidence_refs: list[str]
    visibility: str
    temporal_validity: str
    contradiction_score: float
```

---

## New Confidence Scoring

Instead of binary labels.

### Confidence Inputs

| Signal | Weight |
|---|---|
| Retrieval relevance | 25% |
| Semantic similarity | 20% |
| Multi-source agreement | 20% |
| Freshness | 10% |
| Memory certainty | 10% |
| Tool verification | 15% |

---

## Confidence Levels

| Score | Meaning |
|---|---|
| 0.90–1.00 | Grounded |
| 0.75–0.89 | Reliable |
| 0.55–0.74 | Soft inference |
| 0.35–0.54 | Weak evidence |
| <0.35 | Unsafe |

---

## Unsafe Output Handling

If confidence < 0.35:

Instead of hallucinating:

Kuro responds naturally:

```text
I don't currently have enough grounded evidence to answer that precisely.
```

NOT:

```text
[UNKNOWN]
```

---

# 8. Retrieval & Grounding Improvements

## NEW MODULE

### `retrieval_quality.py`

---

## Functions

### `score_retrieval_quality()`

Evaluates:

- semantic overlap
- entity alignment
- temporal alignment
- contradiction risk
- chunk redundancy
- retrieval saturation

---

### `detect_context_bleed()`

Detects:

- cross-user contamination
- unrelated semantic drift
- stale references
- hallucinated continuity

---

### `calculate_evidence_density()`

Ensures:

- answer claims are proportionate to evidence.

Prevents:

- “over-answer hallucination.”

---

# 9. AutoRAG Enhancement

## Current Weakness

AutoRAG only handles:

- relevant
- ambiguous
- irrelevant

---

# NEW STATES

```python
retrieval_grade = {
    "grounded",
    "partial",
    "weak",
    "contradictory",
    "stale",
    "irrelevant"
}
```

---

## New Flow

```text
Retrieval
   ↓
Quality Scoring
   ↓
Contradiction Check
   ↓
Freshness Check
   ↓
Evidence Density Check
   ↓
Decision
```

---

# 10. Contradiction Detection Layer

## NEW MODULE

### `contradiction_detector.py`

Purpose:

Detect conflicting retrieval results.

Especially for:

- research
- finance
- compliance
- memory
- timeline continuity

---

## Example

If memory says:

```text
User uses Ubuntu.
```

but latest retrieval says:

```text
Migrated to Fedora.
```

Kuro should:

- prefer newer evidence
- mention ambiguity naturally
- avoid absolute statements

---

# 11. Persona System Refactor

# Current Problem

Personas are monolithic.

---

# NEW ARCHITECTURE

## Persona Composition Engine

Split persona into layers.

---

## NEW STRUCTURE

```python
PersonaProfile(
    cognition_layer,
    tone_layer,
    expertise_layer,
    interaction_layer,
    behavioral_constraints,
    verbosity_profile,
    challenge_profile,
)
```

---

# Proposed Persona Stack

## A. Cognitive Layer

Defines:

- reasoning depth
- skepticism
- initiative
- challenge intensity

---

## B. Tone Layer

Defines:

- conversational warmth
- formality
- sentence cadence
- humor allowance
- directness

---

## C. Expertise Layer

Defines:

- domain grounding
- retrieval preference
- external search policy
- precision strictness

---

## D. Interaction Layer

Defines:

- proactive behavior
- coaching style
- questioning frequency
- summarization style

---

# 12. Persona Enhancements

## Advisor Persona

### Current

Very protocol-heavy.

### Improve Into

"Research Director"

Behavior:

- strategic
- intellectually sharp
- naturally adversarial
- less robotic
- uses challenge naturally

Add:

- novelty sensitivity
- literature skepticism
- timeline continuity
- dissertation memory anchoring

---

## Auditor Persona

### Improve Into

"Principal QA Architect"

Behavior:

- concise
- surgical
- brutally precise
- evidence-demanding
- low emotional noise

Add:

- architecture consistency scoring
- technical debt awareness
- migration-risk commentary
- regression awareness

---

## Tactical Persona

### Improve Into

"Systems Incident Commander"

Behavior:

- fast
- structured
- operational
- practical
- low theory

Add:

- rollback awareness
- blast radius maps
- runtime impact estimation
- observability-first thinking

---

## Chill Persona

### Improve Into

"Natural Companion"

Behavior:

- relaxed
- intelligent
- non-corporate
- naturally adaptive

Reduce:

- overexplaining
- forced structure
- robotic formatting

---

## Chancellor Persona

### Improve Into

"Strategic Financial Operator"

Add:

- portfolio awareness
- risk framing
- macro context synthesis
- scenario simulation

---

## Consultant Persona

### Improve Into

"Enterprise Transformation Advisor"

Add:

- stakeholder sensitivity
- executive framing
- compliance translation layer
- implementation realism

---

# 13. Persona Runtime State

## NEW MODULE

```text
persona_runtime.py
```

---

## Dynamic Persona State

Instead of static prompts.

Kuro tracks:

```python
PersonaRuntimeState(
    user_stress_level,
    interaction_depth,
    recent_topic,
    conversation_formality,
    response_density,
    challenge_tolerance,
)
```

This enables:

- adaptive tone
- conversational pacing
- intelligent verbosity
- emotional realism

---

# 14. Memory System Improvements

# Problems Detected

## A. Over-Aggressive Semantic Retrieval

Mem0 retrieval may:

- retrieve semantically related but contextually wrong memories.

---

## B. Weak Temporal Weighting

Old memories can overpower recent context.

---

## C. Memory Drift

Repeated summarization risks semantic mutation.

---

# Proposed Fixes

## NEW FILE

```text
memory_validation.py
```

---

## Functions

### `validate_memory_relevance()`

Checks:

- temporal fit
- entity fit
- topic fit
- recency
- contradiction

---

### `apply_temporal_decay_weighting()`

Older memories become weaker unless:

- pinned
- repeated
- reinforced
- marked canonical

---

### `prevent_memory_mutation()`

Prevents summary chains from changing facts.

---

# 15. Database — Schema Additions

## New Tables

---

## `epistemic_claims`

```sql
CREATE TABLE epistemic_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    message_id TEXT,
    claim_text TEXT,
    source_type TEXT,
    confidence REAL,
    contradiction_score REAL,
    visibility TEXT,
    created_at DATETIME
);
```

Purpose:

Internal audit trail.

NOT user-visible.

---

## `retrieval_quality_log`

```sql
CREATE TABLE retrieval_quality_log (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    retrieval_grade TEXT,
    confidence REAL,
    evidence_density REAL,
    freshness_score REAL,
    contradiction_score REAL,
    created_at DATETIME
);
```

---

## `persona_runtime_state`

```sql
CREATE TABLE persona_runtime_state (
    username TEXT,
    session_id TEXT,
    formality REAL,
    verbosity REAL,
    challenge_level REAL,
    interaction_depth REAL,
    updated_at DATETIME
);
```

---

## `memory_integrity_log`

```sql
CREATE TABLE memory_integrity_log (
    id INTEGER PRIMARY KEY,
    memory_id TEXT,
    integrity_score REAL,
    drift_detected INTEGER,
    contradiction_detected INTEGER,
    created_at DATETIME
);
```

---

# 16. LangGraph Refactor

## New Nodes

### Add BEFORE response generation

```text
retrieval_quality_node
confidence_scoring_node
contradiction_detection_node
```

---

## Add AFTER generation

```text
epistemic_annotation_node
response_sanitization_node
style_harmonization_node
```

---

# New Flow Diagram

```text
START
  ↓
memory_retrieval_node
  ↓
retrieval_quality_node
  ↓
query_transform_node
  ↓
contradiction_detection_node
  ↓
confidence_scoring_node
  ↓
response_generation_node
  ↓
epistemic_annotation_node
  ↓
response_sanitization_node
  ↓
style_harmonization_node
  ↓
memory_write_node
  ↓
END
```

---

# 17. SSE Streaming Safety Layer

## Critical Improvement

Currently leakage may occur DURING token streaming.

Need:

```text
token_stream
   ↓
stream_buffer
   ↓
sanitization_pass
   ↓
SSE_emit
```

---

## NEW MODULE

### `stream_safety.py`

Functions:

- `sanitize_stream_chunk()`
- `detect_policy_leakage()`
- `block_internal_metadata()`

---

# 18. Hallucination Prevention Improvements

## Add Retrieval Anchoring

LLM should reference:

- retrieved chunk IDs
- evidence confidence
- memory timestamps

INTERNALLY ONLY.

This strengthens grounding without exposing internals.

---

## Add Claim Budgeting

Current density control is good.

Improve with:

```python
max_claims = evidence_density * confidence_factor
```

---

## Add Hallucination Penalty Loop

If unsupported claims detected:

- regenerate response section.
- not entire response.

---

# 19. Clean Tree (Proposed)

```text
kuro_backend/
├── intelligence/
│   ├── epistemic_engine.py
│   ├── confidence_engine.py
│   ├── provenance_tracker.py
│   ├── contradiction_detector.py
│   ├── retrieval_quality.py
│   ├── response_sanitizer.py
│   ├── grounding_validator.py
│   ├── uncertainty_renderer.py
│   └── stream_safety.py
│
├── personas/
│   ├── persona_profiles.py
│   ├── persona_runtime.py
│   ├── tone_engine.py
│   ├── cognition_profiles.py
│   └── expertise_profiles.py
│
├── memory/
│   ├── memory_validation.py
│   ├── temporal_weighting.py
│   ├── contradiction_memory_guard.py
│   └── semantic_integrity.py
│
├── langgraph/
│   ├── nodes/
│   │   ├── retrieval_quality_node.py
│   │   ├── confidence_node.py
│   │   ├── sanitization_node.py
│   │   └── contradiction_node.py
│   └── flows/
│       └── sovereign_grounding_flow.py
```

---

# 20. Migration Plan

# Phase 1 — Anti-Leak Emergency Patch

Priority: CRITICAL

Tasks:

- Add `response_sanitizer.py`
- Strip visible labels.
- Add stream sanitization.
- Add hard regex leakage blocker.
- Keep internal audit trail only.

Risk: LOW

---

# Phase 2 — Epistemic Engine Refactor

Tasks:

- Replace label-based system.
- Introduce structured claim objects.
- Add confidence engine.
- Add contradiction scoring.

Risk: MEDIUM

---

# Phase 3 — Persona Modularization

Tasks:

- Split persona layers.
- Add runtime adaptive state.
- Reduce prompt rigidity.
- Add style harmonizer.

Risk: MEDIUM

---

# Phase 4 — Memory Integrity System

Tasks:

- Add memory validation.
- Add temporal weighting.
- Add semantic drift prevention.
- Add contradiction guard.

Risk: MEDIUM-HIGH

---

# Phase 5 — Full Grounding Intelligence

Tasks:

- Add retrieval quality scoring.
- Add evidence density.
- Add confidence routing.
- Add partial-regeneration loop.

Risk: HIGH

---

# 21. Recommended Immediate Priority

## TOP PRIORITY

### 1. Remove ALL visible epistemic labels.

This is the single most important fix.

---

### 2. Add response sanitization before SSE output.

Prevents runtime leakage.

---

### 3. Separate internal provenance from natural-language rendering.

Architecturally mandatory.

---

### 4. Modularize persona system.

Will dramatically improve:

- naturalness
- adaptability
- immersion
- realism

---

### 5. Add retrieval quality scoring.

This is the next major anti-hallucination leap.

---

# 22. Expected Outcomes

After implementation:

## User Experience

Kuro becomes:

- more natural
- more intelligent-feeling
- less robotic
- more adaptive
- more trustworthy
- more grounded

WITHOUT exposing internal mechanics.

---

## Technical Outcomes

- hallucination rate reduced
- retrieval precision increased
- memory drift reduced
- persona realism improved
- SSE leakage eliminated
- provenance preserved internally
- auditability retained

---

# 23. Compatibility Assessment

## Fully Compatible With Existing Architecture

This plan is compatible with:

- LangGraph orchestration
- Mem0
- ChromaDB
- Phoenix tracing
- current DB structure
- existing personas
- existing AutoRAG
- current scheduler model
- existing SSE streaming

Minimal destructive migration required.

---

# 24. Final Architectural Recommendation

Kuro should evolve from:

```text
Prompt-driven sovereign assistant
```

into:

```text
Grounded Cognitive Runtime
```

Where:

- provenance is internal
- confidence is continuous
- memory is validated
- personas are composable
- uncertainty is natural
- grounding is systemic
- hallucination prevention is architectural

NOT prompt-dependent.

---

# 25. Files Most Critical To Refactor First

Priority order:

1. `epistemic_filter.py`
2. `langgraph_core.py`
3. `personas.py`
4. `memory_coordinator.py`
5. `memory_manager.py`
6. `perpetual_memory.py`
7. `core.py`
8. `llm_utils.py`

---

# 26. Direct Findings From Uploaded Files

## `epistemic_filter.py`

Main architectural issue:

- Post-generation mutation directly affects user-visible response.
- Internal provenance format not isolated.
- Regex-first labeling too tightly coupled to rendering.

---

## `langgraph_core.py`

Strong orchestration foundation.

Needs:

- sanitization node
- stream safety layer
- confidence routing
- contradiction-aware branching

---

## `personas.py`

Extremely strong domain framing.

Weakness:

- too monolithic
- too static
- too protocol-heavy

Needs composable persona runtime.

---

## `memory_coordinator.py`

Very good concurrency architecture.

Needs:

- retrieval quality scoring
- temporal weighting
- context bleed detection
- semantic integrity validation

---

## `memory_manager.py`

Strong foundation.

Needs:

- memory confidence metadata
- anti-drift protections
- contradiction handling
- recency weighting

---

## `perpetual_memory.py`

Good privacy architecture.

Needs:

- stronger semantic validation
- retrieval confidence scoring
- stale memory suppression

---

# 27. Suggested Version Label

## Proposed Release

```text
[V1.0.0 Beta 7] — "Sovereign Grounding"
```

Core themes:

- Anti-Hallucination 2.0
- Invisible Provenance
- Cognitive Runtime
- Persona Intelligence
- Grounded Memory
- Adaptive Sovereign Architecture
