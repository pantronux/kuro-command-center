# Kuro Runtime Abstraction Refactor & Epistemic Rendering Plan
## Invisible Governance Layer + Repository Naming Normalization

---

# PURPOSE

This document defines:

1. The next-stage runtime abstraction refactor for Kuro.
2. The elimination of visible epistemic middleware leakage.
3. The transition toward invisible provenance rendering.
4. Repository-wide naming normalization.
5. Removal of implementation-phase naming artifacts such as:

```text
CANVAS_1
CANVAS_2
CANVAS_3
```

from:
- runtime code,
- function names,
- environment variables,
- classes,
- constants,
- module identifiers,
- telemetry labels,
- database references,
- internal execution paths.

Comments (#) are allowed to preserve historical implementation context.

---

# PRIMARY PROBLEM IDENTIFIED

Current runtime behavior still exposes:

```text
internal epistemic middleware
```

through visible UI artifacts such as:

- [INFERRED]
- [SPECULATIVE]
- [UNKNOWN]
- ⚠ Epistemic Notice

This creates:

- immersion breaking,
- middleware leakage,
- visible governance scaffolding,
- reduced conversational naturality,
- system-prompt feeling,
- non-human rendering behavior.

The cognition quality itself is improving.

The remaining problem is:

```text
presentation abstraction leakage
```

NOT:

```text
core reasoning quality
```

---

# TARGET ARCHITECTURE DIRECTION

Kuro should evolve toward:

```text
Invisible Epistemic Governance
```

where:

- provenance exists internally,
- confidence scoring exists internally,
- hallucination risk exists internally,
- source classification exists internally,
- forensic traceability exists internally,

BUT:

all user-facing rendering becomes:

```text
naturalized conversational cognition
```

---

# DESIGN PHILOSOPHY

## CURRENT (BAD)

```text
classification
↓
visible label injection
↓
response
```

Example:

```text
[INFERRED]
⚠ Epistemic Notice
```

---

## TARGET (GOOD)

```text
classification
↓
linguistic adaptation
↓
natural epistemic phrasing
↓
response
```

Example:

Instead of:

```text
[INFERRED]
```

Use:

```text
“It is likely that...”
```

or:

```text
“One possible interpretation is...”
```

---

# IMPLEMENTATION REQUIREMENTS

Before implementation:

READ:

```text
SYSTEM_MAP.md
```

The refactor MUST:

- preserve runtime stability,
- avoid cognition regression,
- maintain governance integrity,
- preserve forensic traceability,
- maintain audit logging,
- avoid breaking existing production flows.

---

# SECTION 1 — INVISIBLE EPISTEMIC RENDERING LAYER

## OBJECTIVE

Replace:

```text
visible epistemic tags
```

with:

```text
natural linguistic modulation
```

---

# REQUIRED NEW MODULE

```text
runtime/rendering/
├── epistemic_renderer.py
├── linguistic_modulation.py
├── confidence_phrasing.py
├── provenance_rendering.py
└── conversational_uncertainty.py
```

---

# REQUIRED FUNCTIONS

## 1. render_epistemic_response()

Purpose:

Convert internal epistemic classifications into:

```text
human-natural uncertainty language
```

---

## 2. apply_confidence_modulation()

Maps:

```text
confidence score
→
linguistic phrasing intensity
```

Example:

HIGH CONFIDENCE:

```text
“This strongly suggests...”
```

MEDIUM:

```text
“This appears to indicate...”
```

LOW:

```text
“One possible interpretation is...”
```

---

## 3. suppress_internal_labels()

Hard-removes:

- [INFERRED]
- [SPECULATIVE]
- [UNKNOWN]
- [VERIFIED]
- Epistemic Notice blocks

from:

```text
final conversational output
```

while preserving:

- audit logs,
- internal telemetry,
- forensic provenance.

---

# SECTION 2 — DUAL-LAYER EPISTEMIC ARCHITECTURE

## LAYER 1 — INTERNAL

Invisible.

Used for:

- provenance,
- hallucination scoring,
- governance,
- retrieval source tracking,
- audit trail,
- forensic reconstruction.

---

## LAYER 2 — USER RENDERING

Visible.

Used for:

- conversational naturality,
- contextual caution,
- probabilistic phrasing,
- linguistic confidence signaling.

---

# SECTION 3 — REPOSITORY NAMING NORMALIZATION

## OBJECTIVE

Remove implementation-phase artifacts such as:

```text
CANVAS_1
CANVAS_2
CANVAS_3
```

from:

- runtime variables,
- feature flags,
- classes,
- functions,
- environment variables,
- module names,
- telemetry labels,
- database schema names,
- internal execution identifiers.

---

# IMPORTANT RULE

These names are allowed ONLY inside:

```python
# comments
```

for historical implementation context.

They MUST NOT exist in:

- executable code,
- runtime naming,
- architecture identifiers,
- production interfaces.

---

# CURRENT PROBLEM EXAMPLE

BAD:

```python
KURO_CANVAS3_MEMORY_CANONICALIZATION_ENABLED
```

BAD:

```python
KURO_CANVAS3_COGNITIVE_BUDGET_ENABLED
```

These names leak:

```text
internal implementation history
```

and create:

- poor architectural aesthetics,
- unclear runtime semantics,
- implementation-coupled naming.

---

# TARGET REFACTOR EXAMPLES

OLD:

```python
KURO_CANVAS3_MEMORY_CANONICALIZATION_ENABLED
```

NEW:

```python
KURO_MEMORY_CANONICALIZATION_ENABLED
```

---

OLD:

```python
KURO_CANVAS3_COGNITIVE_BUDGET_ENABLED
```

NEW:

```python
KURO_COGNITIVE_BUDGET_ENABLED
```

---

OLD:

```python
KURO_CANVAS3_TOOL_GOVERNANCE_ENABLED
```

NEW:

```python
KURO_TOOL_GOVERNANCE_ENABLED
```

---

# CRITICAL NORMALIZATION RULE

After removal:

```text
NO DOUBLE UNDERSCORES
```

MUST exist.

BAD:

```python
KURO__MEMORY_ENABLED
```

GOOD:

```python
KURO_MEMORY_ENABLED
```

---

# REQUIRED REPOSITORY-WIDE AUDIT

Perform full repository scan for:

- CANVAS_1
- CANVAS_2
- CANVAS_3
- CANVAS1
- CANVAS2
- CANVAS3
- implementation-phase aliases
- temporary migration naming
- internal roadmap identifiers

---

# REQUIRED NORMALIZATION AREAS

## 1. ENV VARIABLES

## 2. CONFIG FILES

## 3. FUNCTION NAMES

## 4. CLASS NAMES

## 5. MODULE NAMES

## 6. DATABASE TABLES

## 7. TELEMETRY LABELS

## 8. FEATURE FLAGS

## 9. LOGGER PREFIXES

## 10. API RESPONSE FIELDS

---

# SECTION 4 — REQUIRED IMPLEMENTATION PLAN

Before coding:

Generate:

```text
Implementation Plan
```

ONLY.

DO NOT directly execute refactor.

---

# IMPLEMENTATION PLAN MUST INCLUDE

## 1. Repository Audit Findings

Identify:

- all implementation-phase naming leaks,
- all visible epistemic rendering leaks,
- all internal middleware exposure points.

---

## 2. Clean Refactor Mapping Table

Example:

| Old Name | New Name |
|---|---|
| KURO_CANVAS3_MEMORY_CANONICALIZATION_ENABLED | KURO_MEMORY_CANONICALIZATION_ENABLED |

---

## 3. Epistemic Rendering Refactor Design

Explain:

- invisible provenance architecture,
- linguistic modulation system,
- confidence rendering strategy,
- natural uncertainty phrasing.

---

## 4. Flow Diagram

Required diagrams:

### A. Internal Epistemic Flow

### B. Conversational Rendering Flow

### C. Repository Naming Migration Flow

### D. Runtime Governance Isolation

---

## 5. Clean Tree Structure

Must include:

```text
runtime/rendering/
```

and all new rendering modules.

---

## 6. Backward Compatibility Strategy

Explain:

- migration safety,
- compatibility aliases,
- config fallback handling,
- telemetry continuity.

---

## 7. Feature Flag Strategy

ALL new rendering behavior MUST be:

```text
default OFF
```

until validated.

---

## 8. Regression Risk Analysis

Must analyze:

- hallucination regression,
- governance weakening,
- rendering instability,
- confidence misrepresentation,
- audit trace loss.

---

## 9. Repository Naming Validation Pass

Must include:

- duplicate underscore detection,
- naming sanitation,
- environment normalization,
- semantic naming consistency.

---

# SECTION 5 — TARGET END STATE

Kuro should eventually feel like:

```text
grounded research cognition
```

NOT:

```text
middleware wrapped in visible governance labels
```

The user should:

- feel epistemic caution,
- feel grounded reasoning,
- feel uncertainty awareness,

WITHOUT:

seeing raw runtime governance mechanics.

---

# FINAL INSTRUCTION FOR CODEX

FIRST RESPONSE MUST ONLY:

```text
Generate the complete Implementation Plan.
```

DO NOT:

- modify files,
- execute refactors,
- rename modules,
- edit environment variables,
- create migrations,
- or change runtime behavior yet.

The plan will be reviewed before implementation begins.

