# Kuro AI V2.0.0 Beta 1 — Codex CLI Execution Prompts
# "Sovereign Runtime" — Force Major Version Migration
# Grouped by Phase (8 Prompts)
#
# PREREQUISITE: V1.1.0 improvement prompts (7 prompts) harus sudah dieksekusi.
# Usage: codex "<paste prompt content here>"
# Run from repo root. Eksekusi berurutan — setiap prompt bergantung pada hasil prompt sebelumnya.
# Antara setiap prompt: pytest tests/ -x --tb=short

---

---
# GAP ANALYSIS — Apa yang TIDAK ada di V2 Plan tapi wajib ada
#
# Setelah membaca V1.1.0 (SYSTEM_MAP) dan V2.0.0 plan, ini gap yang kamu perlu tahu:
#
# GAP-01: V2 plan ditulis dalam TypeScript (src/runtime/*.ts), tapi codebase aktual adalah Python/FastAPI.
#         Prompt-prompt ini menggunakan Python. Kalau kamu memang mau migrasi ke TS, eksekusi
#         Prompt 0 (Architecture Decision) dulu sebelum yang lain.
#
# GAP-02: V2 plan tidak menyebut migration strategy dari V1 data.
#         8 SQLite DBs + ChromaDB + Mem0 yang sudah berisi data production perlu migration path.
#         Prompt 1 menangani ini via runtime_context column injection.
#
# GAP-03: V2 plan tidak menyebut backward compatibility untuk chat UI yang sudah ada.
#         User yang sedang aktif tidak boleh terdampak saat runtime namespace diaktifkan.
#         Prompt 1 include legacy shim untuk ini.
#
# GAP-04: V2 plan menyebut "Forensic Runtime" di structured output tapi tidak mendefinisikannya.
#         Prompt 4 include forensic sebagai future-compatible stub.
#
# GAP-05: V2 plan tidak menyebut rollback strategy jika boundary guard terlalu strict.
#         Semua prompt include ROLLBACK SWITCH via env var KURO_V2_STRICT_MODE=false.
#
# GAP-06: V2 plan tidak menyebut versioning strategy untuk runtime config YAML itu sendiri.
#         Prompt 1 include config schema versioning.
#
# GAP-07: LangGraph DAG (V1) dan Runtime Registry (V2) perlu coexist selama transisi.
#         Prompt 2 menangani ini via runtime-aware LangGraph wrapper, bukan replace DAG.
---

---
# PROMPT 0 — PHASE 0: ARCHITECTURE BASELINE AUDIT
# Tujuan: Dokumentasi otomatis arsitektur existing sebelum refactor dimulai.
# Output: /docs/architecture/ directory dengan snapshot state V1.
---

```
codex "
You are working on Kuro AI. The codebase is in Python/FastAPI with LangGraph.
Root directory contains: main.py, kuro_backend/, web_interface/, tests/, openclaw_skills/, docs/ (create if missing).

IMPORTANT CONTEXT: This is Phase 0 of a major version migration from V1.1.0 to V2.0.0.
Do NOT change any functional code in this prompt. This is documentation and audit only.

## TASK A0-A — Create Architecture Snapshot Docs

Create the following files. Populate each by reading the actual codebase:

### 1. /docs/architecture/current-runtime-map.md
Content:
- List every Python module in kuro_backend/ with one-line description of its responsibility
- List all APScheduler jobs with their schedule and target function
- List all FastAPI routes grouped by prefix (/api/chat, /api/finances, /api/ingestion, etc.)
- List all SQLite database files and their primary tables
- List all external API dependencies (Gemini, Telegram, yfinance, Serper, NVD, OpenClaw, Mem0, ChromaDB)
- List all environment variables read from config.py
- Identify every location where a global variable is mutated at module level (e.g. module-level dicts, lists, or singletons)

### 2. /docs/architecture/global-state-audit.md
Content:
- For each global mutable variable found: name, module, type, current usage, risk level (LOW/MED/HIGH)
- Specifically flag: any dict or object shared across async request handlers without locking
- List prompt content that is currently defined as module-level constants

### 3. /docs/architecture/leakage-risk-register.md
Content:
- List every location where memory retrieval does NOT filter by user or session
- List every location where a tool can be called without checking the calling context
- List every location where ChromaDB or Mem0 is queried without a namespace/collection filter
- Rate each risk: CRITICAL / HIGH / MEDIUM / LOW

### 4. /docs/architecture/v2-target-runtime-map.md
Content (static, write this content exactly):

```markdown
# Kuro V2.0.0 Target Runtime Map

## Target Runtimes
| runtime_id    | display_name        | Priority |
|---------------|---------------------|----------|
| sovereign     | Sovereign Chat      | P0       |
| qa            | QA Playground       | P0       |
| research      | Research Playground | P1       |
| governance    | Governance Runtime  | P1       |
| compliance    | Compliance Runtime  | P2       |
| forensic      | Forensic Runtime    | P3 (stub)|

## Migration Strategy
- All V1 chat sessions default to runtime_id = 'sovereign'
- New sessions must explicitly declare runtime_id on creation
- Memory namespace convention: kuro.{runtime_id}.{memory_type}
- Backward compat: if runtime_id missing from request, default to 'sovereign' with WARNING log

## Rollback Switch
- KURO_V2_STRICT_MODE=false: boundary guard logs violations but does NOT block access
- KURO_V2_STRICT_MODE=true: boundary guard blocks and raises 403
- Default for Beta 1: false
```

### 5. /docs/architecture/technical-debt-register.md
Content:
- List every TODO, FIXME, HACK, or NOQA comment found in the codebase
- List every function longer than 100 lines
- List every except: pass or bare except blocks
- List every place where print() is used instead of logger

## TASK A0-B — Create V2 Directory Skeleton

Create the following empty directories and placeholder files (do not implement yet):

```
kuro_backend/runtime/
  __init__.py
  runtime_registry.py       # STUB - Phase 1
  runtime_context.py        # STUB - Phase 1
  runtime_loader.py         # STUB - Phase 1
  runtime_policy.py         # STUB - Phase 1
  boundary_guard.py         # STUB - Phase 2

kuro_backend/memory_v2/
  __init__.py
  memory_store.py           # STUB - Phase 3
  memory_router.py          # STUB - Phase 3
  memory_policy.py          # STUB - Phase 3
  conflict_resolver.py      # STUB - Phase 3
  decay_engine.py           # STUB - Phase 3
  provenance_tracker.py     # STUB - Phase 3

kuro_backend/output/
  __init__.py
  schema_registry.py        # STUB - Phase 4
  output_validator.py       # STUB - Phase 4
  output_repair.py          # STUB - Phase 4
  output_normalizer.py      # STUB - Phase 4

kuro_backend/provider/
  __init__.py
  provider_interface.py     # STUB - Phase 5
  provider_router.py        # STUB - Phase 5

config/runtime/
  sovereign.runtime.yaml
  qa.runtime.yaml
  research.runtime.yaml
  governance.runtime.yaml
  compliance.runtime.yaml
  forensic.runtime.yaml     # stub only

evaluation/
  datasets/
  test_suites/
  metrics/
  reports/
  __init__.py
```

Each STUB file should contain only:
- A module docstring explaining what it will do in its Phase
- A single placeholder class or function with NotImplementedError
- A Header Doc block with: Purpose, Target Phase, Dependencies (TBD), Status: STUB

Each .runtime.yaml file should contain the template from the V2 plan.
Populate sovereign.runtime.yaml with:
```yaml
runtime_id: sovereign
display_name: Sovereign Chat
version: 1
memory_namespace: kuro.sovereign
retrieval_scope:
  - sovereign_chat_history
  - sovereign_knowledge
prompt_stack:
  - system.sovereign.base
tools:
  - web_search
  - file_reader
  - market_analysis
  - vulnerability_scan
structured_output_contract: null
allowed_providers:
  - gemini
  - openai
  - claude
fallback_provider: gemini
```

## ACCEPTANCE CRITERIA
- /docs/architecture/ directory exists with all 5 files, each non-empty
- kuro_backend/runtime/, kuro_backend/memory_v2/, kuro_backend/output/, kuro_backend/provider/ all exist
- config/runtime/ has 6 .yaml files
- evaluation/ directory structure created
- No functional code changed
- Run: pytest tests/ -x — all existing tests still pass
"
```

---

---
# PROMPT 1 — PHASE 1: RUNTIME REGISTRY & NAMESPACE SEPARATION
# Tujuan: Implementasi runtime registry + inject runtime_id ke seluruh request pipeline.
# Depends on: Prompt 0 (directory skeleton must exist)
---

```
codex "
You are working on Kuro AI V2.0.0 migration. Python/FastAPI + LangGraph codebase.
Root directory structure was established in Phase 0. Directory kuro_backend/runtime/ exists with STUB files.

## TASK R1-A — Implement RuntimeRegistry

In kuro_backend/runtime/runtime_registry.py (replace STUB):

```python
# --- Header Doc ---
# Purpose: Central registry for all Kuro runtime configurations.
#          Loads runtime YAML configs, caches them, and provides lookup.
# Caller: runtime_loader.py, main.py startup
# Dependencies: pyyaml, config.py, pydantic
# Main Functions: RuntimeRegistry.get(), RuntimeRegistry.list_runtimes(), RuntimeRegistry.reload()
# Side Effects: Reads config/runtime/*.runtime.yaml at startup

from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional
import yaml, logging

logger = logging.getLogger(__name__)

class RuntimeConfig(BaseModel):
    runtime_id: str
    display_name: str
    version: int = 1
    memory_namespace: str
    retrieval_scope: list[str] = []
    prompt_stack: list[str] = []
    tools: list[str] = []
    structured_output_contract: Optional[str] = None
    allowed_providers: list[str] = Field(default=['gemini'])
    fallback_provider: str = 'gemini'
    is_stub: bool = False  # True for forensic and future runtimes

class RuntimeRegistry:
    _cache: dict[str, RuntimeConfig] = {}
    _config_dir: Path = Path('config/runtime')

    @classmethod
    def load_all(cls):
        cls._cache.clear()
        for yaml_file in cls._config_dir.glob('*.runtime.yaml'):
            try:
                data = yaml.safe_load(yaml_file.read_text())
                config = RuntimeConfig(**data)
                cls._cache[config.runtime_id] = config
                logger.info(f'Loaded runtime: {config.runtime_id} (v{config.version})')
            except Exception as e:
                logger.error(f'Failed to load runtime config {yaml_file}: {e}')

    @classmethod
    def get(cls, runtime_id: str) -> RuntimeConfig:
        if not cls._cache:
            cls.load_all()
        config = cls._cache.get(runtime_id)
        if config is None:
            logger.warning(f'Unknown runtime_id={runtime_id}, falling back to sovereign')
            return cls._cache.get('sovereign') or RuntimeConfig(
                runtime_id='sovereign',
                display_name='Sovereign Chat',
                memory_namespace='kuro.sovereign',
            )
        return config

    @classmethod
    def list_runtimes(cls) -> list[RuntimeConfig]:
        if not cls._cache:
            cls.load_all()
        return list(cls._cache.values())

    @classmethod
    def reload(cls):
        cls.load_all()
```

## TASK R1-B — Implement RuntimeContext

In kuro_backend/runtime/runtime_context.py (replace STUB):

```python
# --- Header Doc ---
# Purpose: Request-scoped runtime context. Carries runtime_id through the entire
#          processing pipeline. Replaces hardcoded globals.
# Caller: main.py (FastAPI dependency), langgraph_core.py
# Dependencies: runtime_registry.py
# Main Functions: get_runtime_context() FastAPI dependency, RuntimeContext dataclass

from dataclasses import dataclass, field
from fastapi import Request
from kuro_backend.runtime.runtime_registry import RuntimeRegistry, RuntimeConfig
import logging

logger = logging.getLogger(__name__)

SOVEREIGN_RUNTIME_ID = 'sovereign'

@dataclass
class RuntimeContext:
    runtime_id: str
    config: RuntimeConfig
    request_id: str = ''
    username: str = ''
    chat_id: str = ''

    @property
    def memory_namespace(self) -> str:
        return self.config.memory_namespace

    @property
    def allowed_tools(self) -> list[str]:
        return self.config.tools

    @property
    def prompt_stack(self) -> list[str]:
        return self.config.prompt_stack

def resolve_runtime_context(runtime_id: str | None, username: str = '', chat_id: str = '') -> RuntimeContext:
    '''
    Resolve runtime from runtime_id string.
    If runtime_id is None or unknown: default to sovereign with WARNING.
    '''
    if runtime_id is None:
        import os
        if os.getenv('KURO_V2_STRICT_MODE', 'false').lower() == 'true':
            raise ValueError('runtime_id is required in V2 strict mode')
        logger.warning(f'No runtime_id provided for username={username}, defaulting to sovereign')
        runtime_id = SOVEREIGN_RUNTIME_ID
    config = RuntimeRegistry.get(runtime_id)
    return RuntimeContext(runtime_id=runtime_id, config=config, username=username, chat_id=chat_id)
```

## TASK R1-C — Inject runtime_id into FastAPI Request Pipeline

In main.py:
1. On startup lifespan: call `RuntimeRegistry.load_all()`.
2. Add `runtime_id: str | None = Query(default=None)` parameter to POST /api/chat/stream.
3. Resolve runtime context at the start of the route handler:
   ```python
   ctx = resolve_runtime_context(runtime_id, username=token_data.username, chat_id=chat_id)
   ```
4. Pass `ctx` into `process_chat_with_graph_stream(state, ctx)`.
5. Add GET /api/runtimes route (no auth required) that returns RuntimeRegistry.list_runtimes() as JSON list (excluding stub runtimes, i.e. is_stub=True).
6. Add GET /api/runtimes/{runtime_id} route for single runtime config lookup.

## TASK R1-D — Inject runtime_id into LangGraph State

In kuro_backend/langgraph_core.py:
1. Add `runtime_id: str` and `runtime_namespace: str` fields to KuroState TypedDict.
2. In `process_chat_with_graph_stream`: populate state['runtime_id'] and state['runtime_namespace'] from ctx before invoking graph.
3. In `memory_retrieval_node`: use `state['runtime_namespace']` as ChromaDB collection filter and Mem0 metadata filter instead of any hardcoded namespace.
   Pattern:
   ```python
   namespace = state.get('runtime_namespace', 'kuro.sovereign')
   results = await safe_mem0_retrieve(query, username, namespace=namespace)
   ```
4. In `memory_extraction_node`: tag extracted memories with runtime_id:
   ```python
   await safe_mem0_add(content, username, metadata={'runtime_id': state['runtime_id'], ...})
   ```

## TASK R1-E — Database Migration: Add runtime_id to chat_sessions

In kuro_backend/chat_history.py:
1. In init_db(): add column if not exists:
   ```sql
   ALTER TABLE chat_sessions ADD COLUMN runtime_id TEXT DEFAULT 'sovereign'
   ```
   Use schema guard pattern (try/except OperationalError for 'duplicate column').
2. In create_session(): accept `runtime_id: str = 'sovereign'` parameter, store it.
3. In get_session(): return runtime_id in session dict.
4. In get_history_page(): include runtime_id in response.
5. Migration: UPDATE chat_sessions SET runtime_id = 'sovereign' WHERE runtime_id IS NULL

## TASK R1-F — Config Schema Version Guard

In kuro_backend/runtime/runtime_registry.py:
- Add validation: if yaml version field > KURO_RUNTIME_CONFIG_VERSION (constant = 1), log WARNING and skip loading that config.
- Add constant KURO_RUNTIME_CONFIG_VERSION = 1 to the file.
- Document in /docs/architecture/v2-target-runtime-map.md: 'To upgrade config schema, bump version field and KURO_RUNTIME_CONFIG_VERSION constant together.'

## ACCEPTANCE CRITERIA
- Run: pytest tests/ -x — all V1 tests still pass.
- New test file tests/test_runtime_registry.py:
  - RuntimeRegistry.get('sovereign') returns RuntimeConfig with runtime_id='sovereign'
  - RuntimeRegistry.get('unknown_xyz') returns sovereign fallback
  - resolve_runtime_context(None) logs warning and returns sovereign context
  - resolve_runtime_context('qa') returns QA config with memory_namespace='kuro.qa'
- GET /api/runtimes returns list with at least sovereign and qa
- POST /api/chat/stream with runtime_id=qa still completes successfully (no regression)
- POST /api/chat/stream without runtime_id still works (backward compat, defaults to sovereign)
- All new code includes Header Doc block.
"
```

---

---
# PROMPT 2 — PHASE 2: COGNITIVE BOUNDARY ISOLATION
# Tujuan: Boundary guard yang enforce runtime isolation di memory, tools, dan prompts.
# Depends on: Prompt 1 (RuntimeContext must exist)
---

```
codex "
You are working on Kuro AI V2.0.0 migration. Python/FastAPI + LangGraph codebase.
RuntimeContext and RuntimeRegistry from Phase 1 are implemented and passing tests.

## TASK B2-A — Implement BoundaryGuard

In kuro_backend/runtime/boundary_guard.py (replace STUB):

```python
# --- Header Doc ---
# Purpose: Enforces cognitive isolation between runtimes.
#          Guards memory namespace access, tool access, and prompt stack access.
#          In KURO_V2_STRICT_MODE=false: logs violations but allows access (audit mode).
#          In KURO_V2_STRICT_MODE=true: raises BoundaryViolationError.
# Caller: memory_coordinator.py, langgraph_core.py (tool dispatch), prompt resolution
# Dependencies: runtime_context.py, intelligence_db.py (audit log), config.py
# Main Functions: assert_memory_access, assert_tool_access, assert_prompt_access
# Side Effects: Writes to audit log on violation

import os, logging, hashlib
from kuro_backend.runtime.runtime_context import RuntimeContext
from kuro_backend import intelligence_db

logger = logging.getLogger(__name__)

class BoundaryViolationError(PermissionError):
    pass

def _is_strict() -> bool:
    return os.getenv('KURO_V2_STRICT_MODE', 'false').lower() == 'true'

def _log_violation(ctx: RuntimeContext, resource_type: str, resource_id: str, reason: str):
    msg = f'BOUNDARY VIOLATION | runtime={ctx.runtime_id} | user={ctx.username} | {resource_type}={resource_id} | reason={reason}'
    logger.warning(msg)
    try:
        intelligence_db.add_audit_trail(
            action='boundary_violation',
            details=msg
        )
    except Exception as e:
        logger.error(f'Failed to log boundary violation to DB: {e}')

def assert_memory_access(ctx: RuntimeContext, namespace: str):
    '''Assert that the runtime is allowed to access the given memory namespace.'''
    allowed = [ctx.config.memory_namespace] + _get_shared_namespaces()
    if namespace not in allowed:
        _log_violation(ctx, 'memory_namespace', namespace, f'not in allowed={allowed}')
        if _is_strict():
            raise BoundaryViolationError(f'Runtime {ctx.runtime_id} cannot access namespace {namespace}')

def assert_tool_access(ctx: RuntimeContext, tool_name: str):
    '''Assert that the runtime is allowed to call the given tool.'''
    if tool_name not in ctx.config.tools:
        _log_violation(ctx, 'tool', tool_name, f'not in allowed_tools={ctx.config.tools}')
        if _is_strict():
            raise BoundaryViolationError(f'Runtime {ctx.runtime_id} cannot use tool {tool_name}')

def assert_prompt_access(ctx: RuntimeContext, prompt_id: str):
    '''Assert that the runtime is allowed to use the given prompt.'''
    if prompt_id not in ctx.config.prompt_stack:
        _log_violation(ctx, 'prompt', prompt_id, f'not in prompt_stack={ctx.config.prompt_stack}')
        if _is_strict():
            raise BoundaryViolationError(f'Runtime {ctx.runtime_id} cannot use prompt {prompt_id}')

def _get_shared_namespaces() -> list[str]:
    '''Namespaces accessible by all runtimes (e.g. global knowledge base).'''
    return ['kuro.shared', 'kuro.global_knowledge']
```

## TASK B2-B — Wire BoundaryGuard into Memory Coordinator

In kuro_backend/memory_coordinator.py:
1. Import BoundaryGuard: `from kuro_backend.runtime.boundary_guard import assert_memory_access`
2. In `safe_mem0_retrieve(query, username, namespace=None, ctx=None)`:
   - Add `ctx: RuntimeContext | None = None` parameter
   - If ctx is not None and namespace is not None: call `assert_memory_access(ctx, namespace)`
3. In `execute_mem0_extract_task(content, username, ctx=None)`:
   - If ctx is not None: enforce write to `ctx.memory_namespace` only
4. In `memory_retrieval_node` in langgraph_core.py: pass `ctx` from state into safe_mem0_retrieve calls.

## TASK B2-C — Wire BoundaryGuard into Tool Dispatch

In kuro_backend/langgraph_core.py, in the tool dispatch logic (likely in tool_node or supervisor_node):
1. Before calling any tool: call `boundary_guard.assert_tool_access(ctx, tool_name)`.
2. Get ctx from `state.get('runtime_context')` — store RuntimeContext object in LangGraph state.
   Note: RuntimeContext is not JSON-serializable, store as a dict or store only runtime_id and re-resolve.
   Recommended: store `state['runtime_id']` (string) and re-resolve ctx at each node via `resolve_runtime_context(state['runtime_id'])`.

## TASK B2-D — Runtime Leakage Test Suite

Create tests/test_boundary_guard.py:
```python
# Tests for cognitive boundary isolation

import pytest, os
from unittest.mock import patch, MagicMock
from kuro_backend.runtime.runtime_context import resolve_runtime_context
from kuro_backend.runtime.boundary_guard import (
    assert_memory_access, assert_tool_access, BoundaryViolationError
)

def test_qa_cannot_access_governance_memory_in_strict_mode():
    ctx = resolve_runtime_context('qa', username='test_user')
    with patch.dict(os.environ, {'KURO_V2_STRICT_MODE': 'true'}):
        with pytest.raises(BoundaryViolationError):
            assert_memory_access(ctx, 'kuro.governance')

def test_boundary_violation_logged_in_audit_mode():
    ctx = resolve_runtime_context('qa', username='test_user')
    with patch.dict(os.environ, {'KURO_V2_STRICT_MODE': 'false'}):
        with patch('kuro_backend.runtime.boundary_guard.intelligence_db') as mock_db:
            assert_memory_access(ctx, 'kuro.governance')  # should NOT raise
            mock_db.add_audit_trail.assert_called_once()

def test_qa_can_access_own_namespace():
    ctx = resolve_runtime_context('qa', username='test_user')
    with patch.dict(os.environ, {'KURO_V2_STRICT_MODE': 'true'}):
        # Should not raise
        assert_memory_access(ctx, 'kuro.qa')

def test_all_runtimes_can_access_shared_namespace():
    for runtime_id in ['sovereign', 'qa', 'research']:
        ctx = resolve_runtime_context(runtime_id, username='test_user')
        with patch.dict(os.environ, {'KURO_V2_STRICT_MODE': 'true'}):
            assert_memory_access(ctx, 'kuro.shared')  # should not raise

def test_tool_not_in_registry_blocked_in_strict_mode():
    ctx = resolve_runtime_context('qa', username='test_user')
    with patch.dict(os.environ, {'KURO_V2_STRICT_MODE': 'true'}):
        with pytest.raises(BoundaryViolationError):
            assert_tool_access(ctx, 'market_analysis')  # QA runtime has no market tool

def test_sovereign_can_use_market_tool():
    ctx = resolve_runtime_context('sovereign', username='test_user')
    with patch.dict(os.environ, {'KURO_V2_STRICT_MODE': 'true'}):
        assert_tool_access(ctx, 'market_analysis')  # should not raise
```

## TASK B2-E — Add boundary_violations table to intelligence_db

In kuro_backend/intelligence_db.py:
1. Add table:
   ```sql
   CREATE TABLE IF NOT EXISTS boundary_violations (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       runtime_id TEXT NOT NULL,
       username TEXT NOT NULL,
       resource_type TEXT NOT NULL,
       resource_id TEXT NOT NULL,
       reason TEXT,
       strict_mode INTEGER DEFAULT 0,
       ts TEXT DEFAULT (datetime('now'))
   )
   ```
2. Add function `log_boundary_violation(runtime_id, username, resource_type, resource_id, reason, strict_mode)`.
3. Update boundary_guard.py to call this dedicated function instead of add_audit_trail.
4. Add GET /api/admin/boundary-violations route in main.py (admin only) that returns last 100 violations.

## ACCEPTANCE CRITERIA
- Run: pytest tests/test_boundary_guard.py — all 6 tests pass
- Run: pytest tests/ -x — no regression in V1 tests
- With KURO_V2_STRICT_MODE=false (default): system behaves exactly as V1, violations only logged
- With KURO_V2_STRICT_MODE=true: memory cross-access raises BoundaryViolationError
- GET /api/admin/boundary-violations returns 200 for admin, 403 for non-admin
- All new code includes Header Doc block.
"
```

---

---
# PROMPT 3 — PHASE 3: MEMORY STRATIFICATION & PROVENANCE
# Tujuan: Upgrade memory system ke layered memory dengan provenance, confidence, dan TTL.
# Depends on: Prompt 1 (runtime_namespace), Prompt 2 (boundary guard)
---

```
codex "
You are working on Kuro AI V2.0.0 migration. Python/FastAPI + LangGraph codebase.
RuntimeRegistry, RuntimeContext, and BoundaryGuard from Phases 1-2 are implemented.

## TASK M3-A — Define KuroMemory Schema

In kuro_backend/memory_v2/memory_store.py (replace STUB):

Implement the KuroMemory Pydantic model and a MemoryStore that wraps the existing
SQLite short_term table with V2-compatible provenance fields.

```python
# --- Header Doc ---
# Purpose: V2 Memory Store — unified interface for all memory types with provenance.
#          Wraps existing kuro_short_term.db and extends schema with V2 fields.
#          Does NOT replace Mem0/ChromaDB — sits as metadata/index layer above them.
# Caller: memory_coordinator.py, memory_router.py, langgraph nodes
# Dependencies: memory_manager.py (V1), kuro_backend/db_utils.py, pydantic
# Main Functions: MemoryStore.add(), MemoryStore.retrieve(), MemoryStore.expire()
# Side Effects: Writes to kuro_short_term.db (extended schema)

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime, timedelta
import uuid

MemoryType = Literal['short_term', 'working', 'episodic', 'semantic', 'operational', 'reflective']
MemoryStatus = Literal['active', 'expired', 'conflicted', 'deprecated']

class MemoryProvenance(BaseModel):
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    document_id: Optional[str] = None
    tool_call_id: Optional[str] = None

class KuroMemory(BaseModel):
    id: str = Field(default_factory=lambda: f'mem_{uuid.uuid4().hex[:12]}')
    runtime_id: str
    namespace: str
    type: MemoryType
    content: str
    source: str = 'conversation'
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: MemoryProvenance = Field(default_factory=MemoryProvenance)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: Optional[str] = None
    status: MemoryStatus = 'active'
    username: str = ''
```

Continue in kuro_backend/memory_v2/memory_store.py — implement MemoryStore class with:
- `add(memory: KuroMemory) -> str` — persist to kuro_short_term.db extended table
- `retrieve(namespace, runtime_id, memory_type=None, username=None, limit=20) -> list[KuroMemory]`
  Only return status='active' and not expired entries.
- `expire(memory_id: str)` — set status='expired', updated_at=now
- `mark_conflicted(memory_id: str)` — set status='conflicted'
- `get_by_id(memory_id: str) -> KuroMemory | None`

## TASK M3-B — DB Schema Extension for V2 Memory

In kuro_backend/memory_manager.py (or a new migration in db_utils.py):
Add these columns to short_term table (with schema guard, ALTER TABLE ADD COLUMN IF NOT EXISTS):
```sql
ALTER TABLE short_term ADD COLUMN memory_id TEXT
ALTER TABLE short_term ADD COLUMN runtime_id TEXT DEFAULT 'sovereign'
ALTER TABLE short_term ADD COLUMN namespace TEXT DEFAULT 'kuro.sovereign'
ALTER TABLE short_term ADD COLUMN memory_type TEXT DEFAULT 'short_term'
ALTER TABLE short_term ADD COLUMN confidence REAL DEFAULT 1.0
ALTER TABLE short_term ADD COLUMN provenance_json TEXT DEFAULT '{}'
ALTER TABLE short_term ADD COLUMN expires_at TEXT
ALTER TABLE short_term ADD COLUMN status TEXT DEFAULT 'active'
ALTER TABLE short_term ADD COLUMN source TEXT DEFAULT 'conversation'
```

Run migration to backfill existing rows:
```sql
UPDATE short_term SET runtime_id='sovereign', namespace='kuro.sovereign', status='active' WHERE runtime_id IS NULL
UPDATE short_term SET memory_id='mem_legacy_' || id WHERE memory_id IS NULL
```

## TASK M3-C — Implement ConflictResolver

In kuro_backend/memory_v2/conflict_resolver.py (replace STUB):
```python
# --- Header Doc ---
# Purpose: Detects and resolves conflicting memories within the same namespace.
#          Conflict = two active memories with same runtime_id + username + similar content
#          but different values (e.g. 'user prefers dark mode' vs 'user prefers light mode')
# Caller: MemoryStore.add() — called before inserting new semantic/episodic memory
# Dependencies: memory_store.py, LLM util for similarity check
# Main Functions: detect_conflicts(), resolve_conflict()
# Side Effects: May mark existing memories as 'conflicted'

def detect_conflicts(new_memory: 'KuroMemory', existing_memories: list['KuroMemory']) -> list['KuroMemory']:
    '''
    Simple heuristic: flag as potential conflict if:
    - Same runtime_id + namespace + username
    - Same memory_type (semantic or episodic)
    - Content similarity > 0.7 (use simple keyword overlap for now, LLM-based in future)
    Returns list of potentially conflicting memories.
    '''
    conflicts = []
    new_words = set(new_memory.content.lower().split())
    for mem in existing_memories:
        if mem.type not in ('semantic', 'episodic'):
            continue
        mem_words = set(mem.content.lower().split())
        overlap = len(new_words & mem_words) / max(len(new_words | mem_words), 1)
        if overlap > 0.7:
            conflicts.append(mem)
    return conflicts

def resolve_conflict(store: 'MemoryStore', new_memory: 'KuroMemory', conflicting: list['KuroMemory']):
    '''
    Conflict resolution strategy for Beta 1: newest wins.
    Mark older memories as conflicted, keep new one active.
    Log all conflicts for audit.
    '''
    import logging
    logger = logging.getLogger(__name__)
    for old_mem in conflicting:
        store.mark_conflicted(old_mem.id)
        logger.info(f'Memory conflict: marked {old_mem.id} as conflicted, superseded by new memory for runtime={new_memory.runtime_id}')
```

## TASK M3-D — Implement DecayEngine

In kuro_backend/memory_v2/decay_engine.py (replace STUB):
```python
# --- Header Doc ---
# Purpose: Handles TTL-based expiration and confidence decay for memories.
# Caller: APScheduler job in main.py (daily at 04:00 WIB)
# Dependencies: memory_store.py, db_utils.py
# Main Functions: expire_stale_memories(), decay_confidence()
# Side Effects: Updates memory status in kuro_short_term.db

DEFAULT_TTL_BY_TYPE = {
    'short_term': 1,      # 1 day
    'working': 7,         # 7 days
    'episodic': 90,       # 90 days
    'semantic': 365,      # 1 year
    'operational': 730,   # 2 years
    'reflective': 365,    # 1 year
}

def expire_stale_memories(store):
    '''
    Expire memories past their expires_at.
    Also auto-set expires_at for memories without one based on DEFAULT_TTL_BY_TYPE.
    '''
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    # Fetch all active memories with expires_at < now
    # Call store.expire(memory_id) for each
    # For memories with no expires_at: set based on type + created_at
    pass  # Implement using store.retrieve() and store.expire()
```

## TASK M3-E — Integrate V2 Memory into LangGraph Pipeline

In kuro_backend/langgraph_core.py:
1. In `memory_extraction_node`: after extracting memories via Mem0, also persist to MemoryStore:
   ```python
   from kuro_backend.memory_v2.memory_store import MemoryStore, KuroMemory, MemoryProvenance
   memory = KuroMemory(
       runtime_id=state['runtime_id'],
       namespace=state['runtime_namespace'],
       type='episodic',
       content=extracted_content,
       source='conversation',
       confidence=0.85,
       provenance=MemoryProvenance(session_id=chat_id, message_id=last_message_id),
       username=username,
   )
   MemoryStore().add(memory)
   ```
2. In `memory_retrieval_node`: query MemoryStore for memories in `state['runtime_namespace']` as additional context alongside Mem0 results.

## TASK M3-F — Add DecayEngine to APScheduler

In main.py: add APScheduler job:
```python
scheduler.add_job(
    decay_engine.expire_stale_memories,
    'cron',
    hour=4, minute=0,
    id='memory_decay_job',
    args=[MemoryStore()],
    replace_existing=True
)
```

## ACCEPTANCE CRITERIA
- Run: pytest tests/test_memory_hardening.py tests/test_memory_coordinator_contract.py — all pass
- New test file tests/test_memory_v2.py:
  - KuroMemory validates confidence must be between 0.0 and 1.0
  - MemoryStore.add() rejects memories from wrong namespace (BoundaryViolationError in strict mode)
  - ConflictResolver: two memories with >70% word overlap triggers conflict detection
  - DecayEngine: memory with expires_at in past is marked expired by expire_stale_memories()
  - Memory retrieved by MemoryStore.retrieve() only returns status='active' records
- Existing V1 chat flows unaffected (runtime_id defaults to sovereign)
- All new code includes Header Doc block.
"
```

---

---
# PROMPT 4 — PHASE 4: STRUCTURED OUTPUT ENGINE
# Tujuan: Schema registry + output validator + repair engine untuk operational runtimes.
# Depends on: Prompt 1 (RuntimeConfig.structured_output_contract)
---

```
codex "
You are working on Kuro AI V2.0.0 migration. Python/FastAPI + LangGraph codebase.
Runtime isolation from Phases 1-3 is implemented.

## TASK O4-A — Implement Schema Registry

In kuro_backend/output/schema_registry.py (replace STUB):

```python
# --- Header Doc ---
# Purpose: Central registry for all runtime output schemas.
#          Schemas are Pydantic models + JSON Schema definitions.
#          Versioned: schema_name_v1, schema_name_v2, etc.
# Caller: output_validator.py, runtime_loader.py
# Dependencies: pydantic, RuntimeRegistry
# Main Functions: SchemaRegistry.get_schema(), SchemaRegistry.register()
# Side Effects: None (in-memory registry, loaded at startup)

from pydantic import BaseModel, Field
from typing import Optional, Any
import json

# --- QA Output Schema ---
class TestCaseStep(BaseModel):
    step_number: int
    action: str
    expected_result: str

class TestCase(BaseModel):
    id: str
    title: str
    precondition: str = ''
    steps: list[TestCaseStep]
    expected_result: str
    priority: str = 'medium'
    type: str = 'functional'

class QAOutputV1(BaseModel):
    runtime: str = 'qa'
    task_type: str
    input_summary: str = ''
    assumptions: list[str] = []
    test_cases: list[TestCase]
    risks: list[str] = []
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_version: str = 'qa_output_v1'

# --- Compliance Output Schema ---
class ComplianceFinding(BaseModel):
    id: str
    severity: str
    description: str
    evidence: str = ''
    recommendation: str = ''

class ComplianceOutputV1(BaseModel):
    runtime: str = 'compliance'
    task_type: str
    applicable_rules: list[str] = []
    findings: list[ComplianceFinding] = []
    risk_level: str = 'medium'
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_version: str = 'compliance_output_v1'

# --- Governance Output Schema ---
class GovernancePolicyItem(BaseModel):
    policy_id: str
    description: str
    status: str  # compliant | non-compliant | unknown
    notes: str = ''

class GovernanceOutputV1(BaseModel):
    runtime: str = 'governance'
    task_type: str
    policies_evaluated: list[GovernancePolicyItem] = []
    overall_status: str = 'unknown'
    recommendations: list[str] = []
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_version: str = 'governance_output_v1'

# --- Forensic Output Schema (STUB for future) ---
class ForensicOutputV1(BaseModel):
    runtime: str = 'forensic'
    task_type: str
    findings: list[dict] = []
    timeline: list[dict] = []
    confidence_score: float = 0.0
    schema_version: str = 'forensic_output_v1'

# --- Registry ---
SCHEMA_REGISTRY = {
    'qa_output_v1': QAOutputV1,
    'compliance_output_v1': ComplianceOutputV1,
    'governance_output_v1': GovernanceOutputV1,
    'forensic_output_v1': ForensicOutputV1,
}

class SchemaRegistry:
    @staticmethod
    def get_schema(contract_id: str):
        schema = SCHEMA_REGISTRY.get(contract_id)
        if schema is None:
            raise KeyError(f'Unknown output schema: {contract_id}')
        return schema

    @staticmethod
    def list_schemas() -> list[str]:
        return list(SCHEMA_REGISTRY.keys())
```

## TASK O4-B — Implement OutputValidator + RepairEngine

In kuro_backend/output/output_validator.py (replace STUB):
```python
# --- Header Doc ---
# Purpose: Validates LLM output against the runtime's structured output contract.
#          Returns validated Pydantic model or raises ValidationError.
# Caller: response_node in langgraph_core.py (for operational runtimes)
# Dependencies: schema_registry.py, pydantic
# Main Functions: validate_output(), validate_and_repair()
# Side Effects: Logs validation results to intelligence_db

import json, logging
from pydantic import ValidationError
from kuro_backend.output.schema_registry import SchemaRegistry
from kuro_backend import intelligence_db

logger = logging.getLogger(__name__)

def validate_output(raw_text: str, contract_id: str) -> tuple[bool, Any, str | None]:
    '''
    Parse raw_text as JSON and validate against contract schema.
    Returns: (is_valid, parsed_model_or_None, error_message_or_None)
    '''
    schema_class = SchemaRegistry.get_schema(contract_id)
    try:
        data = json.loads(raw_text)
        model = schema_class(**data)
        intelligence_db.add_audit_trail(action='output_validated', details=f'contract={contract_id} status=valid')
        return True, model, None
    except (json.JSONDecodeError, ValidationError) as e:
        intelligence_db.add_audit_trail(action='output_validated', details=f'contract={contract_id} status=invalid error={str(e)[:200]}')
        return False, None, str(e)
```

In kuro_backend/output/output_repair.py (replace STUB):
```python
# --- Header Doc ---
# Purpose: Attempts to repair invalid structured output using a second LLM call.
#          Called only when primary validation fails.
# Caller: validate_and_repair() in output_validator.py
# Dependencies: output_validator.py, llm_utils.py (or gemini client), schema_registry.py
# Main Functions: attempt_repair()
# Side Effects: Makes additional LLM API call, logs repair attempt

async def attempt_repair(raw_text: str, contract_id: str, error_message: str) -> tuple[bool, Any, str | None]:
    '''
    Send raw_text + error + schema to LLM with instruction to fix the JSON.
    Returns (is_valid, repaired_model_or_None, error_or_None)
    '''
    from kuro_backend.output.schema_registry import SchemaRegistry
    from kuro_backend.output.output_validator import validate_output
    import json

    schema_class = SchemaRegistry.get_schema(contract_id)
    schema_json = json.dumps(schema_class.model_json_schema(), indent=2)

    repair_prompt = f'''The following JSON output failed schema validation.
Error: {error_message}

Required schema:
{schema_json}

Invalid output:
{raw_text}

Return ONLY a corrected JSON object that matches the schema exactly. No explanation, no markdown, no backticks.'''

    # Call LLM (use existing llm_utils or gemini client pattern from codebase)
    # Implement using whatever LLM client is used in llm_utils.py
    try:
        repaired_text = await _call_repair_llm(repair_prompt)
        return validate_output(repaired_text, contract_id)
    except Exception as e:
        return False, None, f'Repair failed: {e}'

async def _call_repair_llm(prompt: str) -> str:
    '''Use existing Gemini/LLM client to call repair. Adapt to actual client in codebase.'''
    # Implement using the actual LLM client pattern found in kuro_backend/
    raise NotImplementedError('Implement using actual LLM client from codebase')
```

## TASK O4-C — Wire Structured Output into response_node

In kuro_backend/langgraph_core.py, in `response_node`:
1. After generating the response text:
   ```python
   runtime_config = RuntimeRegistry.get(state.get('runtime_id', 'sovereign'))
   contract_id = runtime_config.structured_output_contract

   if contract_id:
       is_valid, validated, error = validate_output(response_text, contract_id)
       if not is_valid:
           logger.warning(f'Output validation failed for {contract_id}: {error}. Attempting repair...')
           is_valid, validated, error = await attempt_repair(response_text, contract_id, error)
       if is_valid:
           state['structured_output'] = validated.model_dump()
           state['output_schema_valid'] = True
       else:
           state['structured_output'] = None
           state['output_schema_valid'] = False
           logger.error(f'Structured output repair failed for contract={contract_id}')
   ```
2. Add `structured_output: dict | None` and `output_schema_valid: bool` to KuroState TypedDict.
3. Include `structured_output` in SSE response if present (as a JSON event before the final [DONE]).

## TASK O4-D — Add Schema Routes

In main.py:
1. GET /api/schemas — list all available output schema IDs (no auth required)
2. GET /api/schemas/{contract_id} — return JSON Schema for that contract (no auth required)
3. These routes make it easy for external clients consuming structured output to fetch the schema.

## ACCEPTANCE CRITERIA
- Run: pytest tests/ -x — no regression
- New test file tests/test_structured_output.py:
  - QAOutputV1 validates correctly with valid test case data
  - validate_output returns is_valid=False for malformed JSON
  - validate_output returns is_valid=False for JSON missing required fields
  - Sovereign runtime (contract=None) skips validation entirely (no error)
  - QA runtime with valid output: state['output_schema_valid'] = True after response_node
- GET /api/schemas returns list including 'qa_output_v1'
- GET /api/schemas/qa_output_v1 returns valid JSON Schema
- All new code includes Header Doc block.
"
```

---

---
# PROMPT 5 — PHASE 5: PROVIDER ABSTRACTION LAYER
# Tujuan: Unified provider interface untuk Gemini, OpenAI, Claude, DeepSeek, Ollama.
# Depends on: Prompt 1 (RuntimeConfig.allowed_providers)
---

```
codex "
You are working on Kuro AI V2.0.0 migration. Python/FastAPI + LangGraph codebase.
Phases 1-4 are implemented. Current codebase uses Gemini as primary provider via google-generativeai SDK.

## TASK P5-A — Define Provider Interface

In kuro_backend/provider/provider_interface.py (replace STUB):

```python
# --- Header Doc ---
# Purpose: Unified abstract interface for all LLM providers.
#          Normalizes request/response format across Gemini, OpenAI, Claude, etc.
# Caller: provider_router.py, langgraph_core.py (replaces direct LLM calls)
# Dependencies: abc, pydantic, asyncio
# Main Functions: AIProvider.generate(), AIProvider.stream()
# Side Effects: None (pure interface)

from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import AsyncIterator, Optional, Any

class ProviderRequest(BaseModel):
    prompt: str
    system_prompt: str = ''
    max_tokens: int = 8192
    temperature: float = 0.7
    tools: list[dict] = []
    structured_output_schema: Optional[dict] = None
    context_messages: list[dict] = []  # [{role, content}]

class ProviderUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

class ProviderResponse(BaseModel):
    provider: str
    model: str
    content: str
    structured: Optional[Any] = None
    usage: ProviderUsage = ProviderUsage()
    latency_ms: float = 0.0
    finish_reason: str = 'stop'
    raw: Optional[Any] = None

class ProviderStreamChunk(BaseModel):
    content: str
    is_final: bool = False
    finish_reason: Optional[str] = None

class AIProvider(ABC):
    provider_id: str = ''
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_vision: bool = False
    supports_streaming: bool = True

    @abstractmethod
    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        pass

    @abstractmethod
    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamChunk]:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        '''Check if API key is configured.'''
        pass
```

## TASK P5-B — Implement GeminiProvider (migrate existing calls)

In kuro_backend/provider/gemini_provider.py (new file):
```python
# --- Header Doc ---
# Purpose: Gemini provider implementation wrapping existing google-generativeai usage.
#          Adapter pattern: wraps existing LLM call logic from langgraph_core/llm_utils.
# Caller: ProviderRouter
# Dependencies: provider_interface.py, google-generativeai SDK, config.py
# Main Functions: GeminiProvider.generate(), GeminiProvider.stream()
# Side Effects: Calls Gemini API

import time, os, logging
from kuro_backend.provider.provider_interface import AIProvider, ProviderRequest, ProviderResponse, ProviderStreamChunk, ProviderUsage

logger = logging.getLogger(__name__)

class GeminiProvider(AIProvider):
    provider_id = 'gemini'
    supports_tools = True
    supports_structured_output = True
    supports_vision = True

    def is_available(self) -> bool:
        return bool(os.getenv('GEMINI_API_KEY'))

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        # Migrate existing Gemini generate logic from langgraph_core.py / llm_utils.py here.
        # Wrap in ProviderResponse.
        # Use the actual model name from config (GEMINI_MODEL_NAME or similar).
        start = time.time()
        # ... existing Gemini call logic ...
        latency_ms = (time.time() - start) * 1000
        return ProviderResponse(
            provider='gemini',
            model=os.getenv('GEMINI_MODEL_NAME', 'gemini-2.0-flash'),
            content='',  # fill from actual response
            latency_ms=latency_ms,
        )

    async def stream(self, request: ProviderRequest):
        # Migrate existing Gemini streaming logic from process_chat_with_graph_stream here.
        raise NotImplementedError('Implement from existing Gemini streaming code')
```

## TASK P5-C — Implement ProviderRouter

In kuro_backend/provider/provider_router.py (replace STUB):
```python
# --- Header Doc ---
# Purpose: Routes LLM requests to the correct provider based on RuntimeConfig.
#          Implements fallback: if primary provider fails, tries fallback_provider.
#          Records provider usage for observability.
# Caller: langgraph_core.py (replaces direct LLM calls in nodes)
# Dependencies: provider_interface.py, runtime_registry.py, observability.py
# Main Functions: ProviderRouter.route(), ProviderRouter.stream()
# Side Effects: Calls selected provider API, logs usage

import logging
from kuro_backend.provider.provider_interface import AIProvider, ProviderRequest
from kuro_backend.provider.gemini_provider import GeminiProvider
from kuro_backend.runtime.runtime_registry import RuntimeConfig

logger = logging.getLogger(__name__)

PROVIDER_MAP: dict[str, type[AIProvider]] = {
    'gemini': GeminiProvider,
    # 'openai': OpenAIProvider,   # add when implemented
    # 'claude': ClaudeProvider,   # add when implemented
}

class ProviderRouter:
    def __init__(self, runtime_config: RuntimeConfig):
        self.runtime_config = runtime_config

    def _get_provider(self, provider_id: str) -> AIProvider | None:
        cls = PROVIDER_MAP.get(provider_id)
        if cls is None:
            logger.warning(f'Provider {provider_id} not implemented, skipping')
            return None
        instance = cls()
        if not instance.is_available():
            logger.warning(f'Provider {provider_id} is configured but API key missing')
            return None
        return instance

    async def route(self, request: ProviderRequest):
        for provider_id in [self.runtime_config.allowed_providers[0], self.runtime_config.fallback_provider]:
            provider = self._get_provider(provider_id)
            if provider is None:
                continue
            try:
                response = await provider.generate(request)
                logger.info(f'Provider {provider_id} succeeded | latency={response.latency_ms:.0f}ms')
                return response
            except Exception as e:
                logger.warning(f'Provider {provider_id} failed: {e}, trying fallback...')
        raise RuntimeError(f'All providers failed for runtime={self.runtime_config.runtime_id}')

    async def stream(self, request: ProviderRequest):
        provider_id = self.runtime_config.allowed_providers[0]
        provider = self._get_provider(provider_id)
        if provider is None:
            raise RuntimeError(f'No provider available for runtime={self.runtime_config.runtime_id}')
        async for chunk in provider.stream(request):
            yield chunk
```

## TASK P5-D — Wire ProviderRouter into LangGraph (Non-Breaking)

In kuro_backend/langgraph_core.py:
1. In nodes that directly call Gemini API (e.g. advisor_research_node, response_node):
   - If `state.get('runtime_id')` exists: use ProviderRouter(RuntimeRegistry.get(state['runtime_id'])).route(request)
   - Else (legacy/test path): use existing direct Gemini call as-is
   This makes the change additive and non-breaking for existing tests.
2. In `process_chat_with_graph_stream`: pass RuntimeConfig to ProviderRouter.stream() for streaming.
3. Add `provider_used: str` to LangGraph state — set it from ProviderResponse.provider after each LLM call.

## ACCEPTANCE CRITERIA
- Run: pytest tests/ -x — all existing tests pass
- New test file tests/test_provider_abstraction.py:
  - GeminiProvider.is_available() returns False when GEMINI_API_KEY not set
  - ProviderRouter falls back to fallback_provider when primary fails
  - ProviderRouter raises RuntimeError when all providers fail
  - ProviderResponse model validates required fields
- Sovereign runtime chat still works end-to-end (primary use case unaffected)
- All new code includes Header Doc block.
"
```

---

---
# PROMPT 6 — PHASE 6: QA PLAYGROUND RUNTIME
# Tujuan: QA Runtime sebagai first vertical product di atas Kuro Core.
# Depends on: Prompts 1-5 (runtime isolation, memory, structured output, provider)
---

```
codex "
You are working on Kuro AI V2.0.0 migration. Python/FastAPI + LangGraph codebase.
All infrastructure from Phases 1-5 is in place: RuntimeRegistry, BoundaryGuard, MemoryStore, SchemaRegistry, ProviderRouter.

## TASK Q6-A — Implement QA Runtime Module

Create kuro_backend/playground/qa/ directory with:

### kuro_backend/playground/qa/__init__.py
Empty.

### kuro_backend/playground/qa/qa_runtime.py
```python
# --- Header Doc ---
# Purpose: QA Playground runtime orchestrator. Coordinates requirement parsing,
#          testcase generation, Gherkin conversion, and structured output validation.
# Caller: main.py QA-specific routes, langgraph_core.py when runtime_id='qa'
# Dependencies: RuntimeRegistry('qa'), MemoryStore, SchemaRegistry, ProviderRouter,
#               requirement_parser.py, testcase_generator.py, cucumber_generator.py
# Main Functions: QARuntime.process_request()
# Side Effects: Writes memories to kuro.qa namespace, logs telemetry

from kuro_backend.runtime.runtime_registry import RuntimeRegistry
from kuro_backend.runtime.runtime_context import resolve_runtime_context
from kuro_backend.output.schema_registry import QAOutputV1
from kuro_backend.output.output_validator import validate_output, validate_and_repair
from kuro_backend.playground.qa.requirement_parser import parse_requirements
from kuro_backend.playground.qa.testcase_generator import generate_testcases
from kuro_backend.playground.qa.cucumber_generator import convert_to_gherkin
import logging

logger = logging.getLogger(__name__)

class QARuntime:
    def __init__(self, username: str, chat_id: str):
        self.ctx = resolve_runtime_context('qa', username=username, chat_id=chat_id)
        self.config = RuntimeRegistry.get('qa')

    async def process_request(self, user_input: str, task_type: str = 'testcase_generation') -> dict:
        '''
        Main entry point for QA Playground requests.
        task_type: testcase_generation | cucumber_generation | regression_analysis | requirement_interpretation
        '''
        logger.info(f'QARuntime.process_request | user={self.ctx.username} | task={task_type}')

        if task_type == 'requirement_interpretation':
            parsed = await parse_requirements(user_input, self.ctx)
            return {'task_type': task_type, 'result': parsed}

        elif task_type == 'testcase_generation':
            test_cases = await generate_testcases(user_input, self.ctx)
            output = QAOutputV1(
                task_type='testcase_generation',
                input_summary=user_input[:200],
                test_cases=test_cases,
                confidence_score=0.85,
            )
            return {'task_type': task_type, 'structured_output': output.model_dump()}

        elif task_type == 'cucumber_generation':
            test_cases = await generate_testcases(user_input, self.ctx)
            gherkin = await convert_to_gherkin(test_cases, self.ctx)
            return {'task_type': task_type, 'gherkin': gherkin, 'test_cases': [tc.model_dump() for tc in test_cases]}

        else:
            raise ValueError(f'Unknown QA task_type: {task_type}')
```

### kuro_backend/playground/qa/requirement_parser.py
```python
# --- Header Doc ---
# Purpose: Interprets natural language requirements and extracts structured assumptions.
# Caller: QARuntime.process_request()
# Dependencies: ProviderRouter, RuntimeContext
# Main Functions: parse_requirements()
# Side Effects: LLM API call, stores parsed result in QA memory namespace

async def parse_requirements(raw_requirement: str, ctx) -> dict:
    '''
    Use LLM to extract:
    - Main functionality described
    - Implicit assumptions
    - Edge cases to consider
    - Ambiguities requiring clarification
    Returns structured dict.
    '''
    from kuro_backend.provider.provider_router import ProviderRouter
    from kuro_backend.provider.provider_interface import ProviderRequest
    from kuro_backend.runtime.runtime_registry import RuntimeRegistry
    import json

    prompt = f'''You are a QA analyst. Parse the following requirement and extract:
1. main_functionality: one sentence
2. assumptions: list of implicit assumptions
3. edge_cases: list of edge cases to test
4. ambiguities: list of unclear aspects

Requirement: {raw_requirement}

Respond ONLY in JSON with keys: main_functionality, assumptions, edge_cases, ambiguities'''

    router = ProviderRouter(RuntimeRegistry.get('qa'))
    response = await router.route(ProviderRequest(prompt=prompt, max_tokens=1000, temperature=0.3))
    try:
        return json.loads(response.content)
    except json.JSONDecodeError:
        return {'main_functionality': raw_requirement, 'assumptions': [], 'edge_cases': [], 'ambiguities': []}
```

### kuro_backend/playground/qa/testcase_generator.py
```python
# --- Header Doc ---
# Purpose: Generates structured test cases from requirements using LLM.
# Caller: QARuntime.process_request()
# Dependencies: ProviderRouter, schema_registry.TestCase
# Main Functions: generate_testcases()
# Side Effects: LLM API call

async def generate_testcases(requirement: str, ctx) -> list:
    '''
    Generate list of TestCase objects from a requirement string.
    Prompts LLM to return JSON array matching TestCase schema.
    '''
    from kuro_backend.provider.provider_router import ProviderRouter
    from kuro_backend.provider.provider_interface import ProviderRequest
    from kuro_backend.runtime.runtime_registry import RuntimeRegistry
    from kuro_backend.output.schema_registry import TestCase, TestCaseStep
    import json

    schema = TestCase.model_json_schema()
    prompt = f'''You are a QA engineer. Generate comprehensive test cases for this requirement.

Requirement: {requirement}

Return a JSON array of test case objects. Each object must match this schema:
{json.dumps(schema, indent=2)}

Include: positive tests, negative tests, boundary tests, and edge cases.
Respond ONLY with a JSON array. No explanation, no markdown.'''

    router = ProviderRouter(RuntimeRegistry.get('qa'))
    response = await router.route(ProviderRequest(prompt=prompt, max_tokens=2000, temperature=0.3))

    try:
        raw_list = json.loads(response.content)
        return [TestCase(**tc) for tc in raw_list]
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f'testcase_generator failed to parse LLM output: {e}')
        return []
```

### kuro_backend/playground/qa/cucumber_generator.py
```python
# --- Header Doc ---
# Purpose: Converts TestCase objects to Gherkin/Cucumber format.
# Caller: QARuntime.process_request() when task_type='cucumber_generation'
# Dependencies: schema_registry.TestCase
# Main Functions: convert_to_gherkin()
# Side Effects: LLM API call for natural language Gherkin generation

async def convert_to_gherkin(test_cases: list, ctx) -> str:
    '''
    Convert list of TestCase objects to Gherkin feature file format.
    Returns Gherkin string.
    '''
    import json
    from kuro_backend.provider.provider_router import ProviderRouter
    from kuro_backend.provider.provider_interface import ProviderRequest
    from kuro_backend.runtime.runtime_registry import RuntimeRegistry

    tc_json = json.dumps([tc.model_dump() for tc in test_cases], indent=2)
    prompt = f'''Convert these test cases to Gherkin/Cucumber format.

Test Cases:
{tc_json}

Return a complete .feature file with Feature, Background (if applicable), and Scenario blocks.
Use Given/When/Then/And syntax. Be specific and unambiguous.'''

    router = ProviderRouter(RuntimeRegistry.get('qa'))
    response = await router.route(ProviderRequest(prompt=prompt, max_tokens=2000, temperature=0.2))
    return response.content
```

## TASK Q6-B — QA Playground API Routes

In main.py:
1. Add POST /api/playground/qa/interpret route:
   ```python
   @app.post('/api/playground/qa/interpret')
   async def qa_interpret(body: dict, token_data=Depends(validate_token)):
       runtime = QARuntime(username=token_data.username, chat_id=body.get('chat_id', ''))
       result = await runtime.process_request(body['requirement'], task_type='requirement_interpretation')
       return result
   ```
2. Add POST /api/playground/qa/generate-testcases route (task_type='testcase_generation').
3. Add POST /api/playground/qa/generate-gherkin route (task_type='cucumber_generation').
4. All QA routes require auth (Depends(validate_token)).

## TASK Q6-C — QA Runtime Memory Integration

In kuro_backend/playground/qa/qa_runtime.py, after processing:
1. Store the input requirement and generated test count as episodic memory in kuro.qa namespace:
   ```python
   from kuro_backend.memory_v2.memory_store import MemoryStore, KuroMemory, MemoryProvenance
   memory = KuroMemory(
       runtime_id='qa',
       namespace='kuro.qa',
       type='episodic',
       content=f'Generated {len(test_cases)} test cases for: {user_input[:100]}',
       source='qa_runtime',
       confidence=0.9,
       username=self.ctx.username,
   )
   MemoryStore().add(memory)
   ```

## ACCEPTANCE CRITERIA
- Run: pytest tests/ -x — no regression
- New test file tests/test_qa_playground.py:
  - POST /api/playground/qa/generate-testcases with valid requirement returns structured output with test_cases list
  - QAOutputV1 schema validated on response (output_schema_valid=True)
  - parse_requirements returns dict with keys: main_functionality, assumptions, edge_cases, ambiguities
  - convert_to_gherkin returns string containing 'Scenario' keyword
  - QA runtime cannot write to kuro.sovereign namespace (boundary guard test)
- Manual: POST /api/playground/qa/generate-testcases with 'User can login with email and password' → returns at least 3 test cases
- All new code includes Header Doc block.
"
```

---

---
# PROMPT 7 — PHASE 7: EVALUATION FRAMEWORK + OBSERVABILITY UPGRADE
# Tujuan: Runtime evaluation metrics + upgraded telemetry dengan trace_id per request.
# Depends on: Prompts 1-6 (all runtime infrastructure)
---

```
codex "
You are working on Kuro AI V2.0.0 migration. Python/FastAPI + LangGraph codebase.
All runtime infrastructure from Phases 1-6 is implemented.

## TASK E7-A — Implement Evaluation Framework

Create evaluation/runner.py (NOT in kuro_backend — this is a standalone eval tool):
```python
# --- Header Doc ---
# Purpose: Standalone evaluation runner for Kuro runtime quality metrics.
#          Run via: python -m evaluation.runner --runtime qa --suite leakage
# Caller: CI/CD pipeline, manual evaluation runs
# Dependencies: pytest, kuro_backend (import as library), json
# Main Functions: run_evaluation_suite(), compute_metrics()
# Side Effects: Writes evaluation report to evaluation/reports/

import json, asyncio, datetime
from pathlib import Path

class EvaluationResult:
    def __init__(self, runtime_id: str, suite_id: str):
        self.runtime_id = runtime_id
        self.suite_id = suite_id
        self.hallucination_rate: float = 0.0
        self.domain_leakage_score: float = 0.0
        self.consistency_score: float = 0.0
        self.tool_reliability: float = 0.0
        self.structured_output_validity: float = 0.0
        self.latency_ms_avg: float = 0.0
        self.cases_total: int = 0
        self.cases_passed: int = 0
        self.timestamp: str = datetime.datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return self.__dict__

def run_suite(runtime_id: str, suite_id: str) -> EvaluationResult:
    result = EvaluationResult(runtime_id, suite_id)
    dataset_path = Path(f'evaluation/datasets/{runtime_id}_{suite_id}.json')
    if not dataset_path.exists():
        raise FileNotFoundError(f'No dataset for {runtime_id}/{suite_id}')
    cases = json.loads(dataset_path.read_text())
    result.cases_total = len(cases)
    # Run each case, compare expected vs actual
    # Implement per-suite logic in evaluation/test_suites/{runtime_id}_{suite_id}.py
    return result

def save_report(result: EvaluationResult):
    report_path = Path(f'evaluation/reports/{result.runtime_id}_{result.suite_id}_{result.timestamp[:10]}.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result.to_dict(), indent=2))
    print(f'Report saved: {report_path}')
```

Create evaluation/datasets/qa_leakage.json (sample dataset):
```json
[
  {
    "id": "leakage_001",
    "input": "What is the governance policy for data retention?",
    "runtime": "qa",
    "expected_behavior": "boundary_safe",
    "expected_keywords_absent": ["governance policy", "retention period", "GDPR"],
    "notes": "QA runtime should not answer governance questions with governance memory"
  },
  {
    "id": "leakage_002",
    "input": "Generate test cases for user login",
    "runtime": "qa",
    "expected_behavior": "qa_output",
    "expected_schema": "qa_output_v1",
    "notes": "Core QA task should return valid structured output"
  }
]
```

## TASK E7-B — Add trace_id to Every Request

In main.py:
1. Add a middleware that generates a `trace_id` for every request:
   ```python
   import uuid
   from starlette.middleware.base import BaseHTTPMiddleware

   class TraceMiddleware(BaseHTTPMiddleware):
       async def dispatch(self, request, call_next):
           trace_id = request.headers.get('X-Trace-ID') or f'trace_{uuid.uuid4().hex[:16]}'
           request.state.trace_id = trace_id
           response = await call_next(request)
           response.headers['X-Trace-ID'] = trace_id
           return response

   app.add_middleware(TraceMiddleware)
   ```
2. Pass `trace_id` into LangGraph state: `state['trace_id'] = request.state.trace_id`.
3. Include `trace_id` in all intelligence_db audit log entries (add column to audit_trail if not present).
4. Include `trace_id` in SSE response headers.

## TASK E7-C — CognitionTrace: Unified Telemetry Event

Create kuro_backend/telemetry/cognition_trace.py:
```python
# --- Header Doc ---
# Purpose: Per-request cognition trace. Captures full pipeline execution record
#          for observability, debugging, and drift detection.
# Caller: langgraph_core.py (at start and end of each request)
# Dependencies: intelligence_db.py, observability.py
# Main Functions: CognitionTrace.start(), CognitionTrace.record_node(), CognitionTrace.finish()
# Side Effects: Writes to cognition_traces table in intelligence_db

from dataclasses import dataclass, field
import time, json, logging
from kuro_backend import intelligence_db

logger = logging.getLogger(__name__)

@dataclass
class CognitionTrace:
    trace_id: str
    runtime_id: str
    username: str
    chat_id: str
    started_at: float = field(default_factory=time.time)
    nodes_executed: list[str] = field(default_factory=list)
    memory_namespaces_accessed: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    provider_used: str = ''
    output_schema: str = ''
    schema_valid: bool = False
    leakage_detected: bool = False
    boundary_violations: int = 0
    latency_ms: float = 0.0
    error: str = ''

    def record_node(self, node_name: str):
        self.nodes_executed.append(node_name)

    def record_memory_access(self, namespace: str):
        if namespace not in self.memory_namespaces_accessed:
            self.memory_namespaces_accessed.append(namespace)

    def record_tool_call(self, tool_name: str):
        self.tools_called.append(tool_name)

    def finish(self, error: str = ''):
        self.latency_ms = (time.time() - self.started_at) * 1000
        self.error = error
        self._persist()

    def _persist(self):
        try:
            intelligence_db.log_cognition_trace(self)
        except Exception as e:
            logger.error(f'Failed to persist cognition trace {self.trace_id}: {e}')
```

Add `log_cognition_trace(trace: CognitionTrace)` to intelligence_db.py:
1. Add table `cognition_traces`:
   ```sql
   CREATE TABLE IF NOT EXISTS cognition_traces (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       trace_id TEXT UNIQUE NOT NULL,
       runtime_id TEXT NOT NULL,
       username TEXT NOT NULL,
       chat_id TEXT,
       nodes_executed TEXT,       -- JSON array
       memory_namespaces TEXT,    -- JSON array
       tools_called TEXT,         -- JSON array
       provider_used TEXT,
       output_schema TEXT,
       schema_valid INTEGER DEFAULT 0,
       leakage_detected INTEGER DEFAULT 0,
       boundary_violations INTEGER DEFAULT 0,
       latency_ms REAL,
       error TEXT,
       ts TEXT DEFAULT (datetime('now'))
   )
   ```
2. Implement log_cognition_trace that inserts a row with JSON-serialized lists.

## TASK E7-D — Wire CognitionTrace into LangGraph

In kuro_backend/langgraph_core.py:
1. At the start of `process_chat_with_graph_stream`:
   ```python
   trace = CognitionTrace(
       trace_id=state.get('trace_id', f'trace_{uuid.uuid4().hex[:8]}'),
       runtime_id=state.get('runtime_id', 'sovereign'),
       username=state.get('username', ''),
       chat_id=state.get('chat_id', ''),
   )
   state['_trace'] = trace
   ```
2. In each node function: call `state['_trace'].record_node(node_name)` at the start.
3. In memory_retrieval_node: call `state['_trace'].record_memory_access(namespace)`.
4. In tool_node: call `state['_trace'].record_tool_call(tool_name)`.
5. On completion or error: call `state['_trace'].finish(error=error_message_if_any)`.

## TASK E7-E — Runtime Health Dashboard Route

In main.py:
1. Add GET /api/admin/runtime-health route (admin only) that aggregates from cognition_traces:
   ```python
   # Return for each runtime_id:
   # - total requests (last 24h)
   # - avg latency_ms
   # - schema_valid rate (% of requests)
   # - boundary_violations count
   # - error rate
   # - most used tools
   # - most accessed memory namespaces
   ```
2. Query cognition_traces WHERE ts > datetime('now', '-24 hours'), GROUP BY runtime_id.
3. Return as JSON for dashboard consumption.

## TASK E7-F — Vocabulary Sanitization Layer (Phase 9 from V2 plan)

In kuro_backend/telemetry/ (reuse module for vocab):
Create kuro_backend/vocabulary/sanitizer.py:
```python
# --- Header Doc ---
# Purpose: Sanitizes internal technical terminology from user-facing responses.
#          Replaces system jargon with natural language equivalents.
#          Developer mode (KURO_DEV_MODE=true) bypasses sanitization.
# Caller: response_node in langgraph_core.py (post-processing step)
# Dependencies: config.py
# Main Functions: sanitize_response()
# Side Effects: None (pure text transform)

import os, re

VOCAB_MAP = {
    r'\bMem0\b': 'Memory System',
    r'\bepisodic buffer\b': 'context history',
    r'\bretrieval topology\b': 'knowledge search scope',
    r'\bgovernance runtime\b': 'Governance Workspace',
    r'\bsemantic memory\b': 'knowledge memory',
    r'\boperational memory\b': 'system configuration memory',
    r'\bchromadb\b': 'Knowledge Base',
    r'\blanggraph\b': 'reasoning pipeline',
    r'\bboundary guard\b': 'access control',
    r'\bvector store\b': 'knowledge index',
    r'\bembedding\b': 'knowledge representation',
    r'\bchunk\b': 'content segment',
    r'\bRAG\b': 'knowledge-grounded response',
    r'\bLLM\b': 'AI model',
}

def sanitize_response(text: str) -> str:
    if os.getenv('KURO_DEV_MODE', 'false').lower() == 'true':
        return text  # bypass in dev mode
    for pattern, replacement in VOCAB_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text
```

In kuro_backend/langgraph_core.py, in `response_node`:
- After generating final response text: `response_text = sanitize_response(response_text)`
- Only apply if runtime is NOT sovereign (or make it configurable per runtime via runtime.yaml flag `vocabulary_sanitization: true/false`)

## ACCEPTANCE CRITERIA
- Run: pytest tests/ -x — no regression
- New test file tests/test_observability_v2.py:
  - CognitionTrace.finish() calls intelligence_db.log_cognition_trace
  - GET /api/admin/runtime-health returns 200 for admin with runtime stats
  - TraceMiddleware adds X-Trace-ID header to all responses
  - trace_id is consistent across trace object, SSE response header, and DB record for same request
- New test file tests/test_vocabulary_sanitizer.py:
  - sanitize_response('Mem0 updated') returns 'Memory System updated'
  - sanitize_response bypassed when KURO_DEV_MODE=true
  - All VOCAB_MAP patterns tested
- Evaluation dataset evaluation/datasets/qa_leakage.json exists and is valid JSON
- All new code includes Header Doc block.
"
```

---
# END OF V2 PROMPTS
#
# EXECUTION ORDER:
#   Prompt 0 (Audit)     → Prompt 1 (Runtime Registry)   → Prompt 2 (Boundary Guard)
#   → Prompt 3 (Memory)  → Prompt 4 (Structured Output)  → Prompt 5 (Provider)
#   → Prompt 6 (QA Playground)  → Prompt 7 (Evaluation + Observability)
#
# COMBINED V1 + V2 TOTAL: 15 prompts (7 V1 + 8 V2)
# V1 prompts must be executed FIRST before any V2 prompt.
#
# ROLLBACK SWITCH (always available):
#   KURO_V2_STRICT_MODE=false  → boundary guard logs only, no blocking (default)
#   KURO_V2_STRICT_MODE=true   → full isolation enforcement
#   KURO_DEV_MODE=true         → bypass vocabulary sanitization, show internal terms
#
# DEFINITION OF DONE — V2.0.0 Beta 1:
#   [ ] All 8 V2 prompts executed without test regression
#   [ ] GET /api/runtimes returns sovereign + qa minimum
#   [ ] POST /api/playground/qa/generate-testcases returns QAOutputV1-valid JSON
#   [ ] boundary_violations table logging violations
#   [ ] cognition_traces table populated per request
#   [ ] GET /api/admin/runtime-health returns runtime stats
#   [ ] evaluation/datasets/qa_leakage.json present
#   [ ] All existing V1 functionality unchanged (backward compat preserved)
