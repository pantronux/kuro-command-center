# Kuro Playground — Integrity UI & Forensic Trust Workflow Plan
## Investigator-Facing Integrity Rendering, Verification Flows, and Evidence Trust Layer

---

# PURPOSE

This document is a direct follow-up to:

```text
Kuro Playground — Forensic Integrity & Semantic Normalization Enhancement Plan
```

The previous document focused primarily on:

- backend forensic integrity architecture,
- semantic normalization lineage,
- transformation manifests,
- chain-of-custody,
- and evidence preservation.

This document extends that work into:

```text
investigator-facing forensic trust workflows
```

including:

- integrity visualization,
- verification interfaces,
- forensic evidence trust rendering,
- session-level integrity tracking,
- snapshot verification,
- and operational forensic navigation.

---

# IMPORTANT DESIGN PRINCIPLE

Integrity systems must NOT remain:

```text
hidden backend-only metadata
```

If Playground is intended to evolve toward:

```text
AI Forensic Semantic Reconstruction Environment
```

then:

- integrity,
- provenance,
- transformation lineage,
- and verification state

must become:

```text
visible and explainable forensic concepts
```

within the investigator workflow.

---

# CURRENT PROBLEM

Current Playground runtime already stores:

- raw evidence,
- canonical traces,
- execution metadata,
- forensic flags,
- and raw SHA256 values.

However:

integrity is still treated mostly as:

```text
backend artifact hashing
```

rather than:

```text
interactive forensic trust infrastructure
```

---

# TARGET DIRECTION

The runtime should evolve toward:

```text
visible forensic trust orchestration
```

where investigators can:

- verify evidence integrity,
- inspect transformation lineage,
- audit canonical reconstruction,
- validate snapshots,
- and review semantic preservation confidence.

---

# IMPLEMENTATION REQUIREMENT

Before implementation:

READ:

```text
SYSTEM_MAP.md
SYSTEM_MAP_PLAYGROUND.md
```

FIRST.

FIRST RESPONSE MUST ONLY:

```text
Implementation Plan
```

DO NOT directly modify runtime.

---

# SECTION 1 — HISTORY PANEL INTEGRITY RENDERING

## OBJECTIVE

Transform session history from:

```text
execution navigation
```

into:

```text
forensic evidence navigation
```

---

# REQUIRED FEATURES

Each execution/session entry should display:

- Integrity Status
- Raw Evidence Hash
- Canonical Trace Hash
- Snapshot Verification State
- Schema Drift Indicators
- Transformation Integrity State

---

# REQUIRED STATUS TYPES

Example:

```text
VERIFIED
MODIFIED
DRIFTED
UNVERIFIED
PARTIAL
CORRUPTED
```

---

# EXAMPLE UI

```text
Session: playground_session_001
Integrity: VERIFIED
Schema Drift: DETECTED
Canonical Integrity: VALID
Snapshot: VERIFIED
```

---

# REQUIRED VISUAL DESIGN

Integrity indicators should:

- remain minimal,
- readable,
- forensic-oriented,
- and avoid excessive visual noise.

The UI must NOT become:

```text
hash spam
```

---

# SECTION 2 — ARTIFACT DETAIL DRAWER / MODAL

## OBJECTIVE

Provide deep forensic metadata inspection.

---

# REQUIRED FEATURES

When investigator clicks a trace/artifact:

open:

```text
Artifact Integrity Detail View
```

---

# REQUIRED INFORMATION

## Acquisition Metadata

- acquisition timestamp
- provider request ID
- provider model
- runtime version
- schema version

---

## Integrity Metadata

- raw SHA256
- canonical SHA256
- snapshot hash
- export hash
- verification timestamp

---

## Transformation Metadata

- normalization version
- mapping confidence
- semantic loss flags
- unresolved provider aliases
- canonicalization warnings

---

## Provenance Metadata

- execution lineage
- session lineage
- export lineage
- replay lineage

---

# SECTION 3 — QUICK INTEGRITY CHECK PANEL

## OBJECTIVE

Add:

```text
Forensic Integrity Overview
```

inside Playground dashboard.

---

# REQUIRED PANEL

Suggested new panel:

```text
Integrity Overview
```

---

# REQUIRED METRICS

- verified artifacts
- integrity failures
- schema drift events
- orphaned traces
- snapshot mismatches
- unresolved canonical mappings
- corrupted exports

---

# REQUIRED ALERT TYPES

## LOW

Schema drift only.

---

## MEDIUM

Canonical degradation detected.

---

## HIGH

Hash mismatch / corrupted evidence.

---

# SECTION 4 — SESSION INTEGRITY HASHING

## OBJECTIVE

Introduce:

```text
session-level forensic integrity
```

---

# CRITICAL CONCEPT

A session is not just:

```text
list of traces
```

but:

```text
forensic execution timeline
```

---

# REQUIRED FEATURES

Generate:

```text
session_integrity_hash
```

covering:

- execution order
- artifact linkage
- canonical traces
- forensic flags
- transformation manifests

---

# PURPOSE

Detect:

- missing artifacts
- modified traces
- execution tampering
- replay inconsistencies

---

# SECTION 5 — SNAPSHOT VERIFICATION WORKFLOW

## OBJECTIVE

Introduce:

```text
forensic evidence freeze verification
```

---

# REQUIRED FEATURES

## 1. Verify Snapshot Action

Allow investigator to:

```text
revalidate snapshot integrity
```

against:

- stored hashes
- schema version
- transformation manifests
- canonical lineage

---

## 2. Snapshot Status States

Example:

```text
VALID
DRIFTED
PARTIAL
UNVERIFIED
CORRUPTED
```

---

## 3. Snapshot Summary UI

Example:

```text
Snapshot Integrity: VALID
Provider Schema: gemini/1.0.0
Transformation Version: canonical_mapper_v1.2
Replay Compatibility: YES
```

---

# SECTION 6 — EXPORT FORENSIC BUNDLES

## OBJECTIVE

Every export should become:

```text
portable forensic evidence package
```

NOT:

```text
single JSON dump
```

---

# REQUIRED EXPORT STRUCTURE

Example:

```text
session_bundle.zip
├── raw/
├── canonical/
├── manifests/
├── hashes/
├── custody/
├── ontology/
└── reports/
```

---

# REQUIRED FILES

## 1. Raw Provider Artifacts

## 2. Canonical Traces

## 3. Transformation Manifests

## 4. Integrity Verification Files

## 5. Chain-of-Custody Logs

## 6. Ontology Reconstruction Outputs

## 7. Human-readable Forensic Report

---

# SECTION 7 — TRANSFORMATION LINEAGE VISUALIZATION

## OBJECTIVE

Expose:

```text
semantic reconstruction lineage
```

visually.

---

# REQUIRED VISUAL FLOW

Example:

```text
Raw Provider Artifact
↓
Canonical Candidate Layer
↓
Normalization Engine
↓
Canonical Trace
↓
Ontology Reconstruction
↓
Forensic Summary
```

---

# REQUIRED FEATURES

Each step should expose:

- hash state
- transformation version
- mapping confidence
- semantic loss indicators
- schema drift indicators

---

# SECTION 8 — HUMAN-READABLE INTEGRITY EXPLANATIONS

## CURRENT PROBLEM

Hashes alone are insufficient for:

- investigators
- supervisors
- dissertation demonstrations
- non-developer audiences

---

# REQUIRED FEATURE

Generate:

```text
forensic integrity explanations
```

---

# EXAMPLE OUTPUT

```text
The raw provider artifact remains unchanged since acquisition.
Canonical normalization completed successfully.
Schema drift was detected but semantic preservation confidence remains high.
No integrity violations were identified.
```

---

# IMPORTANT RULE

Avoid:

```text
raw cryptographic-only UX
```

The system should communicate:

```text
forensic trust state
```

not merely:

```text
hash existence
```

---

# SECTION 9 — FORENSIC WORKFLOW MODES

## OBJECTIVE

Support different investigator workflows.

---

# REQUIRED MODES

## 1. Quick Review Mode

Minimal integrity overview.

---

## 2. Deep Forensic Mode

Expose:

- lineage
- manifests
- hashes
- schema drift
- mapping confidence
- replay compatibility

---

## 3. Academic Presentation Mode

Human-readable reconstruction summaries.

---

# SECTION 10 — CLEAN TREE STRUCTURE

Suggested additions:

```text
playground/ui/integrity/
├── integrity_badges/
├── integrity_drawers/
├── snapshot_verification/
├── lineage_visualization/
├── forensic_explanations/
└── integrity_panels/
```

---

# SECTION 11 — DATABASE SCHEMA ADDITIONS

Suggested additions:

```text
session_integrity
snapshot_verification
integrity_events
transformation_lineage
export_integrity
forensic_verification_logs
```

---

# SECTION 12 — RISK ANALYSIS

## 1. Integrity Illusion Risk

Avoid:

```text
hash exists = evidence trustworthy
```

Integrity must include:

- provenance
- transformation lineage
- semantic preservation

---

## 2. Over-technical UX Risk

Avoid:

```text
developer-only forensic rendering
```

---

## 3. Semantic Misinterpretation Risk

Do NOT imply:

```text
perfect semantic preservation
```

when confidence is uncertain.

---

## 4. Replay Ambiguity Risk

AI outputs are probabilistic.

Replay validation must distinguish:

- integrity,
- compatibility,
- semantic similarity,
- and deterministic equivalence.

---

# SECTION 13 — TARGET END STATE

The Playground should evolve toward:

```text
interactive forensic trust environment for heterogeneous AI evidence
```

where:

- integrity is visible,
- provenance is explainable,
- transformations are traceable,
- and semantic reconstruction remains auditable.

---

# FINAL INSTRUCTION FOR CODEX

FIRST RESPONSE MUST ONLY:

```text
Generate the complete Implementation Plan.
```

The plan MUST include:

- repository audit,
- UI flow diagrams,
- integrity rendering architecture,
- history workflow integration,