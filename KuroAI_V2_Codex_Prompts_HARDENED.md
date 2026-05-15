# Kuro AI V2.0.0 Beta 1 — Codex CLI Execution Prompts (HARDENED)
# Revision: Post-feedback patch. Semua critical issues dari review sudah ditutup.
# Total: 9 prompts (Prompt -1 safety prep + Prompt 0-7)
#
# CHANGES FROM PREVIOUS VERSION:
# [CRITICAL] Prompt -1 ditambah: git branch, backup DB, file inventory
# [CRITICAL] DecayEngine pass → full implementation
# [CRITICAL] OutputRepair NotImplementedError → safe fallback pattern
# [CRITICAL] GeminiProvider NotImplementedError → KURO_PROVIDER_ROUTER_ENABLED flag
# [CRITICAL] ALTER TABLE IF NOT EXISTS → PRAGMA table_info() pattern
# [HIGH]     /api/runtimes public route → stripped config only
# [HIGH]     boundary_violations → structured fields + trace_id
# [HIGH]     RuntimeContext object dilarang masuk LangGraph state
# [HIGH]     Migration idempotency tests ditambah di semua prompt
# [MEDIUM]   Structured output SSE format test ditambah
# [MEDIUM]   Provider fallback test harus mocked, bukan live API
# [ALL]      Global execution rules ditambah di header setiap prompt

---

═══════════════════════════════════════════════════════════════
GLOBAL EXECUTION RULES — BACA SEBELUM EKSEKUSI PROMPT APAPUN
═══════════════════════════════════════════════════════════════

Tempel rules ini sebagai prefix di setiap sesi Codex jika Codex CLI mendukung --instructions flag.
Jika tidak, paste secara manual sebelum setiap prompt.

```
GLOBAL RULES FOR THIS MIGRATION SESSION:
1. Do NOT leave `pass`, `TODO`, `FIXME`, placeholder return values, or `NotImplementedError`
   in any code path that is wired into a route, scheduler job, or LangGraph node.
   If a feature cannot be fully implemented, guard it behind an env flag defaulting to False/disabled.
2. Do NOT break V1 behavior. POST /api/chat/stream without runtime_id must always work.
3. Do NOT replace existing Gemini streaming logic unless the replacement is fully tested.
   Use feature flags (KURO_PROVIDER_ROUTER_ENABLED, KURO_V2_STRICT_MODE, KURO_DEV_MODE).
4. All database migrations must use PRAGMA table_info() to check existing columns.
   Never use ALTER TABLE ADD COLUMN IF NOT EXISTS (not supported in all SQLite versions).
5. All DB migrations must be idempotent: safe to run multiple times without error or duplicate data.
6. Do NOT store Python objects (RuntimeContext, Pydantic models) in LangGraph state.
   Store only JSON-serializable primitives: str, int, float, bool, list, dict.
7. Public routes must NOT expose internal runtime topology (tools, prompt_stack, memory_namespace,
   providers, retrieval_scope). Only runtime_id, display_name, version are public-safe.
8. All admin routes must use existing admin authorization (Depends(validate_token) + ADMIN_USERNAME check).
9. No real external API calls in tests. All LLM/Telegram/yfinance calls must be mocked.
10. After completing all tasks in a prompt: run `python -m compileall kuro_backend` then
    `pytest tests/ -x --tb=short`. Fix all errors before considering the prompt done.
11. Commit after each successful prompt: `git add . && git commit -m "V2 Phase X: <name>"`
```

EXECUTION PROTOCOL per prompt:
```bash
# Before each prompt:
git status  # must be clean

# After each prompt:
python -m compileall kuro_backend
pytest tests/ -x --tb=short
git diff --stat
git add .
git commit -m "V2 Phase X: <phase name>"
```

---

---
# PROMPT -1 — SAFETY PREPARATION (run this FIRST, before anything else)
# Zero functional code changes. Git + backup only.
---

```
codex "
GLOBAL RULES APPLY. This is the safety preparation step before V2 migration.
Do NOT modify any functional code. This is git and filesystem operations only.

## TASK PREP-A — Git Branch and Tag

Run these shell commands:
1. git checkout -b v2-runtime-migration
2. git tag before-v2-migration
3. Verify: git branch --show-current must output 'v2-runtime-migration'
4. Verify: git tag | grep before-v2-migration must return the tag

## TASK PREP-B — Database Backup

1. Create directory: backups/pre-v2/
2. Find all database files:
   find . -not -path './.git/*' -not -path './backups/*' \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) > backups/pre-v2/db_files_found.txt
3. Copy all found DB files into backups/pre-v2/ preserving relative paths.
4. If .env exists: cp .env backups/pre-v2/.env.backup
5. If chroma* directory exists: cp -r chroma* backups/pre-v2/ 2>/dev/null || true
6. If kuro_memory.json exists: cp kuro_memory.json backups/pre-v2/kuro_memory.json.backup 2>/dev/null || true

## TASK PREP-C — Pre-Migration File Inventory

Create docs/architecture/pre_migration_file_inventory.md with this content
(populate dynamically by reading actual filesystem):

```markdown
# Pre-V2 Migration File Inventory
Generated: {current datetime}
Git commit: {output of: git rev-parse HEAD}

## Database Files
{list all .db/.sqlite/.sqlite3 files found, one per line with size in bytes}

## Config Files
{list .env, config/*.yaml, *.toml, *.ini if present}

## Python Modules (kuro_backend/)
{list all .py files in kuro_backend/ with line count}

## Notes
- This file is generated pre-migration as a rollback reference.
- Restore from backups/pre-v2/ if migration needs full rollback.
- KURO_V2_STRICT_MODE=false is the default rollback switch for behavior-level rollback.
- For schema rollback: restore .db files from backups/pre-v2/.
```

## TASK PREP-D — Verify Clean State

Run: pytest tests/ -x --tb=short
If any tests fail before migration: STOP. Fix V1 test failures before proceeding.
Record the output in backups/pre-v2/pre_migration_test_results.txt.

## ACCEPTANCE CRITERIA
- git branch --show-current == 'v2-runtime-migration'
- git tag | grep before-v2-migration returns the tag
- backups/pre-v2/ directory exists and contains at least one .db file (or is empty if no DB files exist)
- docs/architecture/pre_migration_file_inventory.md exists and contains git commit hash
- pytest passes cleanly (or failure is documented in pre_migration_test_results.txt with explanation)
- No functional code changed. git diff HEAD on kuro_backend/ must be empty.
"
```

---

---
# PROMPT 0 — PHASE 0: ARCHITECTURE BASELINE AUDIT
# Zero functional code changes. Documentation + directory skeleton only.
---

```
codex "
GLOBAL RULES APPLY. This is Phase 0 — documentation and skeleton only.
Do NOT modify any existing functional code.
Run from repo root on branch v2-runtime-migration.

## TASK A0-A — Create Architecture Snapshot Docs

Create docs/architecture/ directory if missing. Create these files by reading the actual codebase:

### docs/architecture/current-runtime-map.md
- Every Python module in kuro_backend/ with one-line responsibility description
- All APScheduler jobs: schedule + target function
- All FastAPI routes grouped by prefix
- All SQLite database files and their primary tables
- All external API dependencies
- All environment variables read from config.py
- Every module-level mutable variable (dicts, lists, singletons) — flag any shared across async handlers

### docs/architecture/global-state-audit.md
- All global mutable variables: name, module, type, usage, risk level (LOW/MED/HIGH)
- Flag: any dict/object shared across async request handlers without locking
- List all prompt content defined as module-level constants

### docs/architecture/leakage-risk-register.md
- Every location where memory retrieval does NOT filter by user/session
- Every location where a tool can be called without checking calling context
- Every location where ChromaDB or Mem0 is queried without namespace/collection filter
- Rate each: CRITICAL / HIGH / MEDIUM / LOW

### docs/architecture/v2-target-runtime-map.md
Write this content exactly:

```markdown
# Kuro V2.0.0 Target Runtime Map

## Target Runtimes
| runtime_id  | display_name        | Priority |
|-------------|---------------------|----------|
| sovereign   | Sovereign Chat      | P0       |
| qa          | QA Playground       | P0       |
| research    | Research Playground | P1       |
| governance  | Governance Runtime  | P1       |
| compliance  | Compliance Runtime  | P2       |
| forensic    | Forensic Runtime    | P3 stub  |

## Migration Strategy
- All V1 sessions default to runtime_id = 'sovereign' (no data loss)
- New sessions declare runtime_id on creation; absent = sovereign + WARNING log
- Memory namespace: kuro.{runtime_id}.{memory_type}
- LangGraph state carries only primitives: runtime_id (str), runtime_namespace (str)

## Feature Flags
- KURO_V2_STRICT_MODE=false   → boundary guard logs violations, never blocks (DEFAULT)
- KURO_V2_STRICT_MODE=true    → boundary guard blocks with 403
- KURO_PROVIDER_ROUTER_ENABLED=false → ProviderRouter disabled, legacy Gemini calls active (DEFAULT)
- KURO_DEV_MODE=false         → vocabulary sanitization active (DEFAULT)
- KURO_DEV_MODE=true          → vocabulary sanitization bypassed

## Rollback
- Behavior rollback: set KURO_V2_STRICT_MODE=false
- Schema rollback: restore DB files from backups/pre-v2/
```

### docs/architecture/technical-debt-register.md
- Every TODO/FIXME/HACK/NOQA comment in codebase
- Every function longer than 100 lines
- Every `except: pass` or bare `except` block
- Every `print()` used instead of logger

## TASK A0-B — Create V2 Directory Skeleton

Create these directories and STUB files. Each stub must contain ONLY:
- Module docstring: purpose + target phase
- One placeholder class/function body with: raise NotImplementedError('STUB - Phase X - not yet implemented')
  BUT mark each stub clearly with KURO_STUB=True attribute so code can check before calling
- Header Doc block: Purpose, Target Phase, Dependencies (TBD), Status: STUB

Directories and files:
```
kuro_backend/runtime/__init__.py
kuro_backend/runtime/runtime_registry.py   # STUB Phase 1
kuro_backend/runtime/runtime_context.py    # STUB Phase 1
kuro_backend/runtime/runtime_loader.py     # STUB Phase 1
kuro_backend/runtime/boundary_guard.py     # STUB Phase 2

kuro_backend/memory_v2/__init__.py
kuro_backend/memory_v2/memory_store.py     # STUB Phase 3
kuro_backend/memory_v2/memory_router.py    # STUB Phase 3
kuro_backend/memory_v2/conflict_resolver.py # STUB Phase 3
kuro_backend/memory_v2/decay_engine.py     # STUB Phase 3
kuro_backend/memory_v2/provenance_tracker.py # STUB Phase 3

kuro_backend/output/__init__.py
kuro_backend/output/schema_registry.py     # STUB Phase 4
kuro_backend/output/output_validator.py    # STUB Phase 4
kuro_backend/output/output_repair.py       # STUB Phase 4
kuro_backend/output/output_normalizer.py   # STUB Phase 4

kuro_backend/provider/__init__.py
kuro_backend/provider/provider_interface.py # STUB Phase 5
kuro_backend/provider/provider_router.py    # STUB Phase 5
kuro_backend/provider/gemini_provider.py    # STUB Phase 5

kuro_backend/vocabulary/__init__.py
kuro_backend/vocabulary/sanitizer.py       # STUB Phase 7

kuro_backend/telemetry/__init__.py
kuro_backend/telemetry/cognition_trace.py  # STUB Phase 7

kuro_backend/playground/__init__.py
kuro_backend/playground/qa/__init__.py
kuro_backend/playground/qa/qa_runtime.py         # STUB Phase 6
kuro_backend/playground/qa/requirement_parser.py # STUB Phase 6
kuro_backend/playground/qa/testcase_generator.py # STUB Phase 6
kuro_backend/playground/qa/cucumber_generator.py # STUB Phase 6

config/runtime/sovereign.runtime.yaml
config/runtime/qa.runtime.yaml
config/runtime/research.runtime.yaml
config/runtime/governance.runtime.yaml
config/runtime/compliance.runtime.yaml
config/runtime/forensic.runtime.yaml

evaluation/__init__.py
evaluation/datasets/.gitkeep
evaluation/test_suites/.gitkeep
evaluation/metrics/.gitkeep
evaluation/reports/.gitkeep
```

Populate config/runtime/sovereign.runtime.yaml:
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
fallback_provider: gemini
vocabulary_sanitization: false
```

Populate config/runtime/qa.runtime.yaml:
```yaml
runtime_id: qa
display_name: QA Playground
version: 1
memory_namespace: kuro.qa
retrieval_scope:
  - qa_requirements
  - qa_testcases
prompt_stack:
  - system.qa.base
  - system.qa.output_contract
tools:
  - testcase_generator
  - cucumber_generator
structured_output_contract: qa_output_v1
allowed_providers:
  - gemini
fallback_provider: gemini
vocabulary_sanitization: true
```

For research, governance, compliance: populate with reasonable defaults following the same schema.
For forensic: add `is_stub: true` field.

## ACCEPTANCE CRITERIA
- Run: pytest tests/ -x — all existing tests still pass (zero functional change)
- All 5 docs/architecture/ files exist and are non-empty
- All kuro_backend/runtime/, memory_v2/, output/, provider/, vocabulary/, telemetry/, playground/ directories exist
- config/runtime/ has 6 .yaml files
- No existing .py file in kuro_backend/ was modified
- python -m compileall kuro_backend returns zero errors
"
```

---

---
# PROMPT 1 — PHASE 1: RUNTIME REGISTRY & NAMESPACE SEPARATION
# Gate 1: test runtime registry + legacy chat backward compat before proceeding
---

```
codex "
GLOBAL RULES APPLY. Branch: v2-runtime-migration. Phase 0 skeleton must exist.

## TASK R1-A — Implement RuntimeRegistry

Replace STUB in kuro_backend/runtime/runtime_registry.py:

```python
# --- Header Doc ---
# Purpose: Central registry for all Kuro runtime configurations.
#          Loads runtime YAML configs and provides lookup with sovereign fallback.
# Caller: runtime_context.py, main.py startup, /api/runtimes routes
# Dependencies: pyyaml, pydantic, pathlib
# Main Functions: RuntimeRegistry.get(), list_runtimes(), reload()
# Side Effects: Reads config/runtime/*.runtime.yaml at startup

from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional
import yaml, logging

logger = logging.getLogger(__name__)
KURO_RUNTIME_CONFIG_VERSION = 1

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
    vocabulary_sanitization: bool = False
    is_stub: bool = False

class RuntimeRegistry:
    _cache: dict[str, RuntimeConfig] = {}
    _config_dir: Path = Path('config/runtime')

    @classmethod
    def load_all(cls):
        cls._cache.clear()
        for yaml_file in sorted(cls._config_dir.glob('*.runtime.yaml')):
            try:
                data = yaml.safe_load(yaml_file.read_text())
                if data.get('version', 1) > KURO_RUNTIME_CONFIG_VERSION:
                    logger.warning(f'Runtime config {yaml_file} version {data["version"]} > supported {KURO_RUNTIME_CONFIG_VERSION}, skipping')
                    continue
                config = RuntimeConfig(**data)
                cls._cache[config.runtime_id] = config
                logger.info(f'Loaded runtime: {config.runtime_id} v{config.version}')
            except Exception as e:
                logger.error(f'Failed to load runtime config {yaml_file}: {e}')
        if 'sovereign' not in cls._cache:
            logger.critical('sovereign runtime config missing! Using hardcoded fallback.')
            cls._cache['sovereign'] = RuntimeConfig(
                runtime_id='sovereign', display_name='Sovereign Chat',
                memory_namespace='kuro.sovereign',
            )

    @classmethod
    def get(cls, runtime_id: str) -> RuntimeConfig:
        if not cls._cache:
            cls.load_all()
        config = cls._cache.get(runtime_id)
        if config is None:
            logger.warning(f'Unknown runtime_id={runtime_id!r}, falling back to sovereign')
            return cls._cache['sovereign']
        return config

    @classmethod
    def list_runtimes(cls, include_stubs: bool = False) -> list[RuntimeConfig]:
        if not cls._cache:
            cls.load_all()
        return [c for c in cls._cache.values() if include_stubs or not c.is_stub]

    @classmethod
    def reload(cls):
        cls.load_all()
```

## TASK R1-B — Implement RuntimeContext (primitives only in state)

Replace STUB in kuro_backend/runtime/runtime_context.py:

```python
# --- Header Doc ---
# Purpose: Request-scoped runtime context. Resolves runtime_id to config.
#          IMPORTANT: RuntimeContext objects must NEVER be stored in LangGraph state.
#          LangGraph state carries only: runtime_id (str), runtime_namespace (str).
# Caller: main.py FastAPI routes, langgraph_core.py node functions
# Dependencies: runtime_registry.py
# Main Functions: resolve_runtime_context(), RuntimeContext

from dataclasses import dataclass
from kuro_backend.runtime.runtime_registry import RuntimeRegistry, RuntimeConfig
import os, logging

logger = logging.getLogger(__name__)
SOVEREIGN_RUNTIME_ID = 'sovereign'

@dataclass
class RuntimeContext:
    runtime_id: str
    config: RuntimeConfig
    username: str = ''
    chat_id: str = ''
    trace_id: str = ''

    @property
    def memory_namespace(self) -> str:
        return self.config.memory_namespace

    @property
    def allowed_tools(self) -> list[str]:
        return self.config.tools

    def to_state_primitives(self) -> dict:
        '''
        Returns only JSON-serializable primitives for LangGraph state injection.
        NEVER put the RuntimeContext object itself into state.
        '''
        return {
            'runtime_id': self.runtime_id,
            'runtime_namespace': self.config.memory_namespace,
        }

def resolve_runtime_context(
    runtime_id: str | None,
    username: str = '',
    chat_id: str = '',
    trace_id: str = '',
) -> RuntimeContext:
    strict = os.getenv('KURO_V2_STRICT_MODE', 'false').lower() == 'true'
    if runtime_id is None:
        if strict:
            raise ValueError('runtime_id required in KURO_V2_STRICT_MODE=true')
        logger.warning(f'No runtime_id provided for username={username!r}, defaulting to sovereign')
        runtime_id = SOVEREIGN_RUNTIME_ID
    config = RuntimeRegistry.get(runtime_id)
    return RuntimeContext(
        runtime_id=runtime_id, config=config,
        username=username, chat_id=chat_id, trace_id=trace_id,
    )
```

## TASK R1-C — Safe SQLite Column Migration Helper

Add this function to kuro_backend/db_utils.py (create if not exists, or add to existing file):

```python
def add_column_if_missing(conn, table: str, column_name: str, column_sql: str):
    '''
    Safely add a column to a SQLite table only if it does not already exist.
    Uses PRAGMA table_info instead of ALTER TABLE IF NOT EXISTS (not universally supported).
    Idempotent: safe to call multiple times.
    '''
    existing_cols = [row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if column_name not in existing_cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column_sql}')
        conn.commit()
        import logging
        logging.getLogger(__name__).info(f'Added column {column_name} to {table}')
```

## TASK R1-D — Inject runtime_id into FastAPI + LangGraph State

In main.py:
1. In lifespan startup: call RuntimeRegistry.load_all()
2. In POST /api/chat/stream route:
   - Add query param: runtime_id: str | None = Query(default=None)
   - Add request import if not present
   - Resolve: ctx = resolve_runtime_context(runtime_id, username=token_data.username, chat_id=chat_id, trace_id=getattr(request.state, 'trace_id', ''))
   - Inject into state using ctx.to_state_primitives():
     state.update(ctx.to_state_primitives())
   - Do NOT store ctx object in state.

3. In kuro_backend/langgraph_core.py:
   - Add to KuroState TypedDict: runtime_id: str, runtime_namespace: str
   - Default values: runtime_id='sovereign', runtime_namespace='kuro.sovereign'
   - In memory_retrieval_node: use state.get('runtime_namespace', 'kuro.sovereign') as namespace filter
   - In memory_extraction_node: tag memories with runtime_id from state

## TASK R1-E — Database Migration: chat_sessions.runtime_id

In kuro_backend/chat_history.py init_db():
Using add_column_if_missing from db_utils:
```python
add_column_if_missing(conn, 'chat_sessions', 'runtime_id', "TEXT DEFAULT 'sovereign'")
```
Then:
```python
conn.execute("UPDATE chat_sessions SET runtime_id='sovereign' WHERE runtime_id IS NULL")
conn.commit()
```

Update create_session() to accept runtime_id='sovereign' param and store it.
Update get_session() to include runtime_id in returned dict.

## TASK R1-F — API Routes (security-hardened)

In main.py:

GET /api/runtimes (public, NO auth required):
Return ONLY safe fields — never expose internal topology:
```python
return [
    {'runtime_id': r.runtime_id, 'display_name': r.display_name, 'version': r.version}
    for r in RuntimeRegistry.list_runtimes(include_stubs=False)
]
```

GET /api/admin/runtimes/{runtime_id} (admin only — full config):
Return full RuntimeConfig including tools, prompt_stack, memory_namespace etc.
Require: token_data.username == settings.ADMIN_USERNAME

## ACCEPTANCE CRITERIA
- Run: python -m compileall kuro_backend → zero errors
- Run: pytest tests/ -x --tb=short → all pass

New test file tests/test_runtime_registry.py:
```python
def test_sovereign_fallback_for_unknown_runtime():
    ctx = resolve_runtime_context('completely_unknown_xyz')
    assert ctx.runtime_id == 'sovereign'

def test_none_runtime_defaults_to_sovereign_with_warning(caplog):
    with caplog.at_level('WARNING'):
        ctx = resolve_runtime_context(None)
    assert ctx.runtime_id == 'sovereign'
    assert 'defaulting to sovereign' in caplog.text

def test_qa_runtime_resolves_correctly():
    ctx = resolve_runtime_context('qa')
    assert ctx.memory_namespace == 'kuro.qa'

def test_to_state_primitives_only_strings():
    ctx = resolve_runtime_context('qa')
    prims = ctx.to_state_primitives()
    assert all(isinstance(v, str) for v in prims.values())
    assert 'runtime_id' in prims
    assert 'runtime_namespace' in prims
    # Must not contain complex objects
    assert 'config' not in prims

def test_add_column_if_missing_idempotent(tmp_path):
    import sqlite3
    from kuro_backend.db_utils import add_column_if_missing
    db = str(tmp_path / 'test.db')
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE test_table (id INTEGER PRIMARY KEY)')
    add_column_if_missing(conn, 'test_table', 'new_col', 'TEXT DEFAULT NULL')
    add_column_if_missing(conn, 'test_table', 'new_col', 'TEXT DEFAULT NULL')  # second call
    cols = [r[1] for r in conn.execute('PRAGMA table_info(test_table)').fetchall()]
    assert cols.count('new_col') == 1  # must not be duplicated

def test_migration_idempotent(tmp_path):
    # init_db called twice must not raise
    import importlib
    # This test verifies chat_history.init_db() is idempotent
    # Implement by calling init_db() twice on a temp DB path
    pass  # implement using actual init_db with monkeypatched DB_PATH

def test_legacy_chat_no_runtime_id_works():
    # POST /api/chat/stream without runtime_id must succeed (backward compat)
    # Use existing test client setup
    # Expected: response defaults to sovereign, no error
    pass  # implement using test client

def test_public_runtimes_route_hides_internal_fields(test_client):
    resp = test_client.get('/api/runtimes')
    assert resp.status_code == 200
    for runtime in resp.json():
        assert 'tools' not in runtime
        assert 'prompt_stack' not in runtime
        assert 'memory_namespace' not in runtime
        assert 'runtime_id' in runtime
        assert 'display_name' in runtime
```

- Implement all `pass` stubs in test file above
- All tests must pass
"
```

---

---
# PROMPT 2 — PHASE 2: COGNITIVE BOUNDARY ISOLATION
# Gate 2: verify audit mode + strict mode before proceeding to memory refactor
---

```
codex "
GLOBAL RULES APPLY. Branch: v2-runtime-migration. Phase 1 must be passing.

## TASK B2-A — Implement BoundaryGuard

Replace STUB in kuro_backend/runtime/boundary_guard.py:

```python
# --- Header Doc ---
# Purpose: Enforces cognitive isolation between runtimes.
#          Default (KURO_V2_STRICT_MODE=false): logs violations, never blocks.
#          Strict (KURO_V2_STRICT_MODE=true): raises BoundaryViolationError.
# Caller: memory_coordinator.py, langgraph_core.py tool dispatch
# Dependencies: runtime_context.py, intelligence_db.py
# Main Functions: assert_memory_access, assert_tool_access, assert_prompt_access
# Side Effects: Writes structured record to boundary_violations table on violation

import os, logging
from kuro_backend.runtime.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)

SHARED_NAMESPACES = frozenset(['kuro.shared', 'kuro.global_knowledge'])

class BoundaryViolationError(PermissionError):
    pass

def _is_strict() -> bool:
    return os.getenv('KURO_V2_STRICT_MODE', 'false').lower() == 'true'

def _record_violation(
    runtime_id: str,
    username: str,
    resource_type: str,
    resource_id: str,
    reason: str,
    trace_id: str = '',
):
    '''Log structured boundary violation to DB and logger. Never raises.'''
    msg = (f'BOUNDARY | runtime={runtime_id} user={username} '
           f'{resource_type}={resource_id!r} reason={reason} trace={trace_id}')
    logger.warning(msg)
    try:
        from kuro_backend import intelligence_db
        intelligence_db.log_boundary_violation(
            runtime_id=runtime_id,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
            strict_mode=_is_strict(),
            trace_id=trace_id,
        )
    except Exception as e:
        logger.error(f'Failed to persist boundary violation to DB: {e}')

def assert_memory_access(ctx: RuntimeContext, namespace: str):
    allowed = {ctx.config.memory_namespace} | SHARED_NAMESPACES
    if namespace not in allowed:
        _record_violation(ctx.runtime_id, ctx.username, 'memory_namespace', namespace,
                         f'not in allowed={sorted(allowed)}', trace_id=ctx.trace_id)
        if _is_strict():
            raise BoundaryViolationError(
                f'Runtime {ctx.runtime_id!r} cannot access namespace {namespace!r}')

def assert_tool_access(ctx: RuntimeContext, tool_name: str):
    if tool_name not in ctx.config.tools:
        _record_violation(ctx.runtime_id, ctx.username, 'tool', tool_name,
                         f'not in allowed_tools={ctx.config.tools}', trace_id=ctx.trace_id)
        if _is_strict():
            raise BoundaryViolationError(
                f'Runtime {ctx.runtime_id!r} cannot use tool {tool_name!r}')

def assert_prompt_access(ctx: RuntimeContext, prompt_id: str):
    if prompt_id not in ctx.config.prompt_stack:
        _record_violation(ctx.runtime_id, ctx.username, 'prompt', prompt_id,
                         f'not in prompt_stack={ctx.config.prompt_stack}', trace_id=ctx.trace_id)
        if _is_strict():
            raise BoundaryViolationError(
                f'Runtime {ctx.runtime_id!r} cannot use prompt {prompt_id!r}')
```

## TASK B2-B — Add boundary_violations Table + log function

In kuro_backend/intelligence_db.py:

1. In init_db() (or init_intelligence_db()), add using add_column_if_missing pattern:
```sql
CREATE TABLE IF NOT EXISTS boundary_violations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    runtime_id TEXT NOT NULL,
    username TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    reason TEXT,
    strict_mode INTEGER DEFAULT 0,
    trace_id TEXT DEFAULT '',
    ts TEXT DEFAULT (datetime('now'))
)
```

2. Add function:
```python
def log_boundary_violation(runtime_id, username, resource_type, resource_id, reason, strict_mode=False, trace_id=''):
    with _conn() as conn:
        conn.execute(
            '''INSERT INTO boundary_violations
               (runtime_id, username, resource_type, resource_id, reason, strict_mode, trace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (runtime_id, username, resource_type, resource_id, reason, int(strict_mode), trace_id)
        )
        conn.commit()
```

## TASK B2-C — Wire BoundaryGuard into Memory Coordinator

In kuro_backend/memory_coordinator.py:
1. Add optional ctx param to safe_mem0_retrieve and execute_mem0_extract_task:
   `ctx: 'RuntimeContext | None' = None`
2. If ctx is not None: call assert_memory_access(ctx, namespace) BEFORE memory access
3. Pass ctx from LangGraph state by re-resolving from runtime_id:
   ```python
   # In nodes that have state available:
   from kuro_backend.runtime.runtime_context import resolve_runtime_context
   ctx = resolve_runtime_context(state.get('runtime_id'), username=state.get('username', ''))
   ```
   Note: resolve fresh from state primitives — do NOT store ctx in state.

## TASK B2-D — Add Admin Route for Violations

In main.py:
GET /api/admin/boundary-violations (admin only):
```python
@app.get('/api/admin/boundary-violations')
async def get_boundary_violations(limit: int = 100, token_data=Depends(validate_token)):
    if token_data.username != settings.ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail='Admin only')
    return intelligence_db.get_recent_boundary_violations(limit=limit)
```

Add get_recent_boundary_violations(limit=100) to intelligence_db.py:
SELECT * FROM boundary_violations ORDER BY ts DESC LIMIT ?

## ACCEPTANCE CRITERIA
- python -m compileall kuro_backend → zero errors
- pytest tests/ -x --tb=short → all pass

New test file tests/test_boundary_guard.py:
```python
import pytest, os
from unittest.mock import patch, MagicMock

def make_ctx(runtime_id='qa'):
    from kuro_backend.runtime.runtime_context import resolve_runtime_context
    return resolve_runtime_context(runtime_id, username='testuser', trace_id='trace_test_001')

def test_qa_cannot_access_governance_memory_strict(monkeypatch):
    monkeypatch.setenv('KURO_V2_STRICT_MODE', 'true')
    from kuro_backend.runtime import boundary_guard
    from importlib import reload; reload(boundary_guard)
    with patch.object(boundary_guard, '_record_violation'):
        with pytest.raises(boundary_guard.BoundaryViolationError):
            boundary_guard.assert_memory_access(make_ctx('qa'), 'kuro.governance')

def test_audit_mode_logs_but_does_not_block(monkeypatch):
    monkeypatch.setenv('KURO_V2_STRICT_MODE', 'false')
    from kuro_backend.runtime import boundary_guard
    from importlib import reload; reload(boundary_guard)
    with patch.object(boundary_guard, '_record_violation') as mock_record:
        boundary_guard.assert_memory_access(make_ctx('qa'), 'kuro.governance')  # no raise
        mock_record.assert_called_once()

def test_violation_includes_trace_id():
    from kuro_backend.runtime import boundary_guard
    recorded = {}
    def capture(**kwargs): recorded.update(kwargs)
    with patch.object(boundary_guard, '_record_violation', side_effect=lambda **kw: recorded.update(kw)):
        pass
    # verify trace_id is in structured record fields
    ctx = make_ctx('qa')
    assert ctx.trace_id == 'trace_test_001'

def test_shared_namespace_accessible_by_all(monkeypatch):
    monkeypatch.setenv('KURO_V2_STRICT_MODE', 'true')
    from kuro_backend.runtime import boundary_guard
    from importlib import reload; reload(boundary_guard)
    for runtime_id in ['sovereign', 'qa', 'research']:
        ctx = make_ctx(runtime_id)
        boundary_guard.assert_memory_access(ctx, 'kuro.shared')  # must not raise

def test_own_namespace_always_allowed(monkeypatch):
    monkeypatch.setenv('KURO_V2_STRICT_MODE', 'true')
    from kuro_backend.runtime import boundary_guard
    from importlib import reload; reload(boundary_guard)
    ctx = make_ctx('qa')
    boundary_guard.assert_memory_access(ctx, 'kuro.qa')  # must not raise

def test_tool_not_in_registry_blocked_strict(monkeypatch):
    monkeypatch.setenv('KURO_V2_STRICT_MODE', 'true')
    from kuro_backend.runtime import boundary_guard
    from importlib import reload; reload(boundary_guard)
    with patch.object(boundary_guard, '_record_violation'):
        with pytest.raises(boundary_guard.BoundaryViolationError):
            boundary_guard.assert_tool_access(make_ctx('qa'), 'market_analysis')

def test_e2e_strict_mode_safe_failure(monkeypatch, test_client):
    '''End-to-end: QA runtime tries sovereign tool → fails safely, no unhandled exception.'''
    monkeypatch.setenv('KURO_V2_STRICT_MODE', 'true')
    # POST to QA chat route with a tool that is sovereign-only
    # Expect: 400 or structured error response, NOT 500
    # Implement using test_client
    pass  # implement with test_client

def test_legacy_chat_unaffected_by_boundary_guard(test_client):
    '''V1 flow without runtime_id must not be affected by boundary guard.'''
    # POST /api/chat/stream without runtime_id
    # Expected: 200, sovereign runtime, no boundary violations logged
    pass  # implement with test_client
```

- All `pass` test stubs must be implemented
- All tests must pass
- GET /api/admin/boundary-violations returns 403 for non-admin JWT
"
```

---

---
# PROMPT 3 — PHASE 3: MEMORY STRATIFICATION & PROVENANCE
# Gate 3: verify migration idempotency + memory retrieval safety before proceeding
---

```
codex "
GLOBAL RULES APPLY. Branch: v2-runtime-migration. Phases 1-2 must be passing.
IMPORTANT: All DB migrations must use add_column_if_missing from db_utils.py.
IMPORTANT: No pass, TODO, or placeholder in any executed production path.

## TASK M3-A — KuroMemory Schema + MemoryStore

Replace STUB in kuro_backend/memory_v2/memory_store.py.

Implement:
1. KuroMemory Pydantic model with fields:
   id (str, default uuid), runtime_id (str), namespace (str),
   type (Literal['short_term','working','episodic','semantic','operational','reflective']),
   content (str), source (str='conversation'), confidence (float, 0-1),
   provenance (nested model with optional session_id, message_id, document_id, tool_call_id),
   created_at (str ISO), updated_at (str ISO), expires_at (Optional[str]),
   status (Literal['active','expired','conflicted','deprecated']='active'),
   username (str='')

2. MemoryStore class backed by kuro_short_term.db with methods:
   - add(memory: KuroMemory) -> str: INSERT into short_term extended table, return memory_id
   - retrieve(namespace, runtime_id, memory_type=None, username=None, limit=20) -> list[KuroMemory]:
     SELECT WHERE status='active' AND (expires_at IS NULL OR expires_at > datetime('now'))
     filtered by namespace and runtime_id
   - expire(memory_id: str): UPDATE SET status='expired', updated_at=now WHERE id=?
   - mark_conflicted(memory_id: str): UPDATE SET status='conflicted'
   - get_by_id(memory_id: str) -> KuroMemory | None

## TASK M3-B — DB Schema Extension (MUST use add_column_if_missing)

In kuro_backend/memory_manager.py or a new kuro_backend/memory_v2/migrations.py,
create function extend_short_term_schema(conn) that calls add_column_if_missing for each:

```python
from kuro_backend.db_utils import add_column_if_missing

def extend_short_term_schema(conn):
    cols = [
        ('memory_id',       "TEXT"),
        ('runtime_id',      "TEXT DEFAULT 'sovereign'"),
        ('namespace',       "TEXT DEFAULT 'kuro.sovereign'"),
        ('memory_type',     "TEXT DEFAULT 'short_term'"),
        ('confidence',      "REAL DEFAULT 1.0"),
        ('provenance_json', "TEXT DEFAULT '{}'"),
        ('expires_at',      "TEXT"),
        ('status',          "TEXT DEFAULT 'active'"),
        ('source',          "TEXT DEFAULT 'conversation'"),
    ]
    for col_name, col_sql in cols:
        add_column_if_missing(conn, 'short_term', col_name, col_sql)

    # Backfill: only update rows where values are NULL (idempotent)
    conn.execute("""
        UPDATE short_term
        SET runtime_id='sovereign', namespace='kuro.sovereign', status='active'
        WHERE runtime_id IS NULL
    """)
    conn.execute("""
        UPDATE short_term
        SET memory_id='mem_legacy_' || CAST(id AS TEXT)
        WHERE memory_id IS NULL
    """)
    conn.commit()
```

Call extend_short_term_schema in memory_manager init_db() or at MemoryStore.__init__.

## TASK M3-C — Implement ConflictResolver (no placeholders)

Replace STUB in kuro_backend/memory_v2/conflict_resolver.py.

```python
def detect_conflicts(new_memory, existing_memories: list) -> list:
    '''
    Flag as potential conflict if:
    - Same runtime_id + namespace + username + memory_type in (semantic, episodic)
    - Word overlap ratio > 0.7 (Jaccard similarity on whitespace-tokenized content)
    Returns list of conflicting memories (may be empty).
    '''
    if new_memory.type not in ('semantic', 'episodic'):
        return []
    new_words = set(new_memory.content.lower().split())
    if not new_words:
        return []
    conflicts = []
    for mem in existing_memories:
        if mem.type not in ('semantic', 'episodic'):
            continue
        if mem.runtime_id != new_memory.runtime_id or mem.namespace != new_memory.namespace:
            continue
        mem_words = set(mem.content.lower().split())
        union = new_words | mem_words
        if not union:
            continue
        overlap = len(new_words & mem_words) / len(union)
        if overlap > 0.7:
            conflicts.append(mem)
    return conflicts

def resolve_conflict(store, new_memory, conflicting: list):
    '''
    Newest wins: mark all conflicting memories as conflicted, keep new one active.
    Logs each conflict. Never raises.
    '''
    import logging
    logger = logging.getLogger(__name__)
    for old_mem in conflicting:
        try:
            store.mark_conflicted(old_mem.id)
            logger.info(f'Conflict: {old_mem.id!r} marked conflicted, superseded by new memory runtime={new_memory.runtime_id!r}')
        except Exception as e:
            logger.error(f'Failed to mark conflicted {old_mem.id!r}: {e}')
```

## TASK M3-D — Implement DecayEngine (FULL — no pass or placeholder)

Replace STUB in kuro_backend/memory_v2/decay_engine.py:

```python
# --- Header Doc ---
# Purpose: TTL-based memory expiration. Scheduled daily at 04:00 WIB.
# Caller: APScheduler in main.py
# Dependencies: memory_store.py, db_utils.py
# Main Functions: expire_stale_memories(store) -> int
# Side Effects: Updates short_term table rows to status='expired'

from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS: dict[str, int] = {
    'short_term':   1,
    'working':      7,
    'episodic':     90,
    'semantic':     365,
    'operational':  730,
    'reflective':   365,
}

def expire_stale_memories(store) -> int:
    '''
    1. For memories without expires_at: compute and set expires_at based on type + created_at.
    2. Expire all active memories where expires_at < utcnow.
    Returns count of memories expired in this run.
    '''
    now = datetime.utcnow()
    expired_count = 0

    try:
        # Step 1: backfill missing expires_at
        all_active = store.retrieve_all_active_without_expiry()
        for mem in all_active:
            ttl_days = DEFAULT_TTL_DAYS.get(mem.type, 90)
            try:
                created = datetime.fromisoformat(mem.created_at)
            except ValueError:
                created = now
            expires_at = (created + timedelta(days=ttl_days)).isoformat()
            store.set_expires_at(mem.id, expires_at)

        # Step 2: expire stale memories
        stale = store.retrieve_stale(as_of=now.isoformat())
        for mem in stale:
            store.expire(mem.id)
            expired_count += 1
            logger.debug(f'Expired memory {mem.id!r} type={mem.type!r} runtime={mem.runtime_id!r}')

        logger.info(f'DecayEngine: expired {expired_count} memories')
    except Exception as e:
        logger.error(f'DecayEngine failed: {e}', exc_info=True)

    return expired_count
```

Add to MemoryStore:
- retrieve_all_active_without_expiry() -> list[KuroMemory]: SELECT WHERE status='active' AND expires_at IS NULL
- retrieve_stale(as_of: str) -> list[KuroMemory]: SELECT WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?
- set_expires_at(memory_id: str, expires_at: str): UPDATE SET expires_at=? WHERE id=?

## TASK M3-E — Register DecayEngine in APScheduler

In main.py:
```python
from kuro_backend.memory_v2.decay_engine import expire_stale_memories
from kuro_backend.memory_v2.memory_store import MemoryStore

scheduler.add_job(
    lambda: expire_stale_memories(MemoryStore()),
    'cron', hour=4, minute=0,
    id='memory_decay_job', replace_existing=True
)
```

## ACCEPTANCE CRITERIA
- python -m compileall kuro_backend → zero errors
- pytest tests/ -x --tb=short → all pass

New test file tests/test_memory_v2.py:
```python
def test_memory_schema_confidence_bounds():
    from kuro_backend.memory_v2.memory_store import KuroMemory
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        KuroMemory(runtime_id='qa', namespace='kuro.qa', type='semantic',
                   content='x', confidence=1.5, username='u')

def test_extend_short_term_schema_idempotent(tmp_path):
    import sqlite3
    from kuro_backend.memory_v2.migrations import extend_short_term_schema
    db_path = str(tmp_path / 'short_term.db')
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE short_term (id INTEGER PRIMARY KEY, content TEXT)')
    conn.commit()
    extend_short_term_schema(conn)
    extend_short_term_schema(conn)  # second call must not raise
    cols = [r[1] for r in conn.execute('PRAGMA table_info(short_term)').fetchall()]
    assert 'runtime_id' in cols
    assert 'status' in cols
    assert cols.count('runtime_id') == 1  # no duplicate

def test_memory_store_retrieve_excludes_expired(tmp_path):
    # Add an expired memory and an active memory, retrieve must return only active
    pass  # implement with real MemoryStore pointed to tmp_path DB

def test_conflict_resolver_detects_high_overlap():
    from kuro_backend.memory_v2.memory_store import KuroMemory
    from kuro_backend.memory_v2.conflict_resolver import detect_conflicts
    mem1 = KuroMemory(runtime_id='qa', namespace='kuro.qa', type='semantic',
                      content='user prefers dark mode interface', username='u')
    mem2 = KuroMemory(runtime_id='qa', namespace='kuro.qa', type='semantic',
                      content='user prefers light mode interface', username='u')
    conflicts = detect_conflicts(mem2, [mem1])
    assert len(conflicts) == 1

def test_decay_engine_expires_stale(tmp_path):
    # Create a memory with expires_at in the past, run expire_stale_memories
    # verify memory.status == 'expired' after run
    pass  # implement with real MemoryStore

def test_decay_engine_returns_count():
    from kuro_backend.memory_v2.decay_engine import expire_stale_memories
    from unittest.mock import MagicMock
    mock_store = MagicMock()
    mock_store.retrieve_all_active_without_expiry.return_value = []
    mock_store.retrieve_stale.return_value = []
    count = expire_stale_memories(mock_store)
    assert count == 0
```
- All pass stubs implemented and passing
"
```

---

---
# PROMPT 4 — PHASE 4: STRUCTURED OUTPUT ENGINE
# Gate 4: verify repair fallback is safe (no NotImplementedError in production path)
---

```
codex "
GLOBAL RULES APPLY. Branch: v2-runtime-migration. Phases 1-3 must be passing.
CRITICAL: output_repair._call_repair_llm must NEVER raise NotImplementedError.
If the LLM client cannot be wired, return None safely and log the failure.

## TASK O4-A — Implement SchemaRegistry

Replace STUB in kuro_backend/output/schema_registry.py.
Implement QAOutputV1, ComplianceOutputV1, GovernanceOutputV1, ForensicOutputV1 (stub model),
and SchemaRegistry.get_schema(contract_id) / list_schemas() as defined in previous prompt.
No changes needed from previous design. Implement fully.

## TASK O4-B — Implement OutputValidator

Replace STUB in kuro_backend/output/output_validator.py:

```python
import json, logging
from pydantic import ValidationError
from kuro_backend.output.schema_registry import SchemaRegistry
from kuro_backend import intelligence_db

logger = logging.getLogger(__name__)

def validate_output(raw_text: str, contract_id: str) -> tuple[bool, object, str | None]:
    '''
    Parse raw_text as JSON and validate against contract schema.
    Returns (is_valid, model_instance_or_None, error_message_or_None).
    Strips markdown code fences before parsing (LLMs often wrap JSON in ```json).
    '''
    schema_class = SchemaRegistry.get_schema(contract_id)
    cleaned = raw_text.strip()
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        cleaned = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])
    try:
        data = json.loads(cleaned)
        model = schema_class(**data)
        intelligence_db.add_audit_trail(
            action='output_validated',
            details=f'contract={contract_id} status=valid'
        )
        return True, model, None
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        error_msg = str(e)[:300]
        intelligence_db.add_audit_trail(
            action='output_validated',
            details=f'contract={contract_id} status=invalid error={error_msg}'
        )
        return False, None, error_msg
```

## TASK O4-C — Implement OutputRepair (SAFE — no NotImplementedError)

Replace STUB in kuro_backend/output/output_repair.py:

```python
# --- Header Doc ---
# Purpose: Attempts to repair invalid structured output using a second LLM call.
#          SAFE FALLBACK: if LLM client unavailable or repair fails, returns (False, None, reason).
#          Never raises NotImplementedError or unhandled exceptions.
# Caller: langgraph_core.py response_node (only when primary validation fails)
# Dependencies: output_validator.py, schema_registry.py, existing LLM client in codebase
# Main Functions: attempt_repair()
# Side Effects: Additional LLM API call on validation failure

import json, logging
from kuro_backend.output.schema_registry import SchemaRegistry
from kuro_backend.output.output_validator import validate_output

logger = logging.getLogger(__name__)

async def attempt_repair(raw_text: str, contract_id: str, error_message: str) -> tuple[bool, object, str | None]:
    '''
    Try to fix invalid LLM output by sending it back to LLM with schema + error context.
    Returns (is_valid, repaired_model_or_None, error_or_None).
    On any failure: returns (False, None, failure_reason) — never raises.
    '''
    try:
        schema_class = SchemaRegistry.get_schema(contract_id)
        schema_json = json.dumps(schema_class.model_json_schema(), indent=2)
        repair_prompt = (
            f'The following output failed schema validation.\n'
            f'Error: {error_message}\n\n'
            f'Required schema:\n{schema_json}\n\n'
            f'Invalid output:\n{raw_text}\n\n'
            f'Return ONLY a corrected JSON object matching the schema. '
            f'No explanation, no markdown backticks.'
        )
        repaired_text = await _call_repair_llm(repair_prompt)
        if repaired_text is None:
            return False, None, 'Repair LLM unavailable'
        return validate_output(repaired_text, contract_id)
    except Exception as e:
        logger.error(f'attempt_repair failed for contract={contract_id}: {e}')
        return False, None, f'Repair exception: {str(e)[:200]}'

async def _call_repair_llm(prompt: str) -> str | None:
    '''
    Calls the existing LLM client for repair.
    Returns response text or None if unavailable/failed.
    Adapt to actual Gemini client pattern found in kuro_backend/llm_utils.py or equivalent.
    '''
    try:
        # Find the existing Gemini/LLM generate function in llm_utils.py or langgraph_core.py.
        # Import and call it with temperature=0.1 (low temp for repair).
        # Example pattern (adapt to actual codebase):
        # from kuro_backend.llm_utils import generate_text
        # return await generate_text(prompt, temperature=0.1, max_tokens=2000)
        #
        # If no such function exists: return None safely.
        # DO NOT import and call raw Gemini SDK here — use existing abstraction.
        from kuro_backend import llm_utils
        if hasattr(llm_utils, 'generate_text'):
            return await llm_utils.generate_text(prompt, temperature=0.1, max_tokens=2000)
        else:
            logger.warning('No generate_text function found in llm_utils, repair unavailable')
            return None
    except Exception as e:
        logger.error(f'_call_repair_llm failed: {e}')
        return None
```

## TASK O4-D — Wire Structured Output into response_node (non-breaking)

In kuro_backend/langgraph_core.py, in response_node:
After generating response text, add:
```python
from kuro_backend.runtime.runtime_registry import RuntimeRegistry
from kuro_backend.output.output_validator import validate_output
from kuro_backend.output.output_repair import attempt_repair

runtime_config = RuntimeRegistry.get(state.get('runtime_id', 'sovereign'))
contract_id = runtime_config.structured_output_contract

state['structured_output'] = None
state['output_schema_valid'] = False

if contract_id:
    is_valid, validated, error = validate_output(response_text, contract_id)
    if not is_valid:
        logger.warning(f'Output validation failed contract={contract_id}: {error[:100]}. Attempting repair.')
        is_valid, validated, error = await attempt_repair(response_text, contract_id, error)
    if is_valid and validated is not None:
        state['structured_output'] = validated.model_dump()
        state['output_schema_valid'] = True
    else:
        logger.error(f'Structured output repair failed contract={contract_id}: {error}')
        # Do NOT crash. Continue with unstructured response. state['structured_output'] remains None.
```

Add to KuroState TypedDict: `structured_output: dict | None` and `output_schema_valid: bool`

SSE streaming: if state['structured_output'] is not None, send before [DONE]:
```
event: structured_output\ndata: {json.dumps(state['structured_output'])}\n\n
```
Then:
```
event: done\ndata: [DONE]\n\n
```

## TASK O4-E — Schema API Routes

GET /api/schemas → list schema IDs (no auth)
GET /api/schemas/{contract_id} → JSON Schema dict (no auth)

## ACCEPTANCE CRITERIA
- python -m compileall kuro_backend → zero errors
- pytest tests/ -x --tb=short → all pass

New test file tests/test_structured_output.py:
```python
def test_validate_output_valid_qa():
    from kuro_backend.output.output_validator import validate_output
    payload = {'task_type': 'testcase_generation', 'test_cases': [], 'schema_version': 'qa_output_v1'}
    ok, model, err = validate_output(json.dumps(payload), 'qa_output_v1')
    assert ok is True
    assert err is None

def test_validate_output_invalid_json():
    from kuro_backend.output.output_validator import validate_output
    ok, model, err = validate_output('not json at all', 'qa_output_v1')
    assert ok is False
    assert model is None
    assert err is not None

def test_validate_output_strips_markdown_fences():
    from kuro_backend.output.output_validator import validate_output
    payload = '```json\n{"task_type": "testcase_generation", "test_cases": []}\n```'
    ok, model, err = validate_output(payload, 'qa_output_v1')
    assert ok is True

def test_attempt_repair_returns_safe_on_llm_unavailable():
    import asyncio
    from unittest.mock import patch
    from kuro_backend.output.output_repair import attempt_repair
    with patch('kuro_backend.output.output_repair._call_repair_llm', return_value=None):
        ok, model, err = asyncio.run(attempt_repair('bad json', 'qa_output_v1', 'parse error'))
    assert ok is False
    assert model is None
    assert 'unavailable' in err.lower() or err is not None

def test_sovereign_runtime_skips_validation():
    # sovereign has structured_output_contract=None → no validation
    from kuro_backend.runtime.runtime_registry import RuntimeRegistry
    config = RuntimeRegistry.get('sovereign')
    assert config.structured_output_contract is None

def test_sse_structured_output_event_format():
    # If structured_output is in state, SSE must emit:
    # event: structured_output\ndata: {...json...}\n\n
    # then event: done\ndata: [DONE]\n\n
    # Test by parsing SSE stream output from a QA runtime chat
    pass  # implement with test_client + SSE stream parser
```
- All pass stubs implemented
"
```

---

---
# PROMPT 5 — PHASE 5: PROVIDER ABSTRACTION (ADAPTER MODE — no streaming replace)
# Gate 5: feature flag KURO_PROVIDER_ROUTER_ENABLED=false by default.
# Streaming not replaced until GeminiProvider.stream() is fully tested.
---

```
codex "
GLOBAL RULES APPLY. Branch: v2-runtime-migration. Phases 1-4 must be passing.
CRITICAL: Do NOT replace existing Gemini streaming in process_chat_with_graph_stream.
          ProviderRouter is adapter-only in this phase. Existing streaming path stays active.
          Feature flag: KURO_PROVIDER_ROUTER_ENABLED (default=false).
          GeminiProvider.stream() stub is allowed ONLY because it is not wired to production path.

## TASK P5-A — Define Provider Interface

Replace STUB in kuro_backend/provider/provider_interface.py.
Implement AIProvider abstract class with ProviderRequest, ProviderResponse,
ProviderUsage, ProviderStreamChunk as defined in previous design. No changes from design.

## TASK P5-B — Add Feature Flag

In kuro_backend/config.py: add KURO_PROVIDER_ROUTER_ENABLED: bool = False

## TASK P5-C — Implement GeminiProvider (generate only — stream is safe stub)

Replace STUB in kuro_backend/provider/gemini_provider.py:

```python
# --- Header Doc ---
# Purpose: Gemini provider wrapping existing Gemini SDK calls from llm_utils.py.
#          generate() is fully implemented. stream() is a STUB (not wired to production).
# Caller: ProviderRouter (only when KURO_PROVIDER_ROUTER_ENABLED=true)
# Dependencies: provider_interface.py, existing Gemini client in kuro_backend/
# Main Functions: GeminiProvider.generate()
# Side Effects: Calls Gemini API (only when feature flag active)

import time, os, logging
from kuro_backend.provider.provider_interface import (
    AIProvider, ProviderRequest, ProviderResponse, ProviderUsage
)

logger = logging.getLogger(__name__)

class GeminiProvider(AIProvider):
    provider_id = 'gemini'
    supports_tools = True
    supports_structured_output = True
    supports_vision = True
    supports_streaming = True  # streaming impl deferred to future phase

    def is_available(self) -> bool:
        return bool(os.getenv('GEMINI_API_KEY'))

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        '''
        Wraps existing Gemini generate call from llm_utils.py or equivalent.
        Adapt import path to actual codebase structure.
        '''
        start = time.time()
        try:
            from kuro_backend import llm_utils
            if not hasattr(llm_utils, 'generate_text'):
                raise AttributeError('generate_text not found in llm_utils')
            content = await llm_utils.generate_text(
                request.prompt,
                system_prompt=request.system_prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
            latency_ms = (time.time() - start) * 1000
            return ProviderResponse(
                provider='gemini',
                model=os.getenv('GEMINI_MODEL_NAME', 'gemini-2.0-flash'),
                content=content or '',
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error(f'GeminiProvider.generate failed: {e}')
            raise

    async def stream(self, request: ProviderRequest):
        '''
        STUB: streaming migration deferred. This method must not be called in production.
        Production streaming uses existing path in langgraph_core.py.
        '''
        raise NotImplementedError(
            'GeminiProvider.stream() is not yet implemented. '
            'Production streaming uses legacy path. '
            'Do not wire this to any route or scheduler.'
        )
```

## TASK P5-D — Implement ProviderRouter

Replace STUB in kuro_backend/provider/provider_router.py:

```python
# --- Header Doc ---
# Purpose: Routes generate() calls to the correct provider based on RuntimeConfig.
#          Implements primary → fallback chain.
#          DISABLED by default: KURO_PROVIDER_ROUTER_ENABLED=false.
#          stream() is NOT implemented here — legacy streaming path remains active.
# Caller: langgraph_core.py nodes (only when feature flag is true)
# Dependencies: provider_interface.py, gemini_provider.py, runtime_registry.py
# Main Functions: ProviderRouter.route()
# Side Effects: LLM API call

import os, logging
from kuro_backend.provider.provider_interface import AIProvider, ProviderRequest
from kuro_backend.provider.gemini_provider import GeminiProvider
from kuro_backend.runtime.runtime_registry import RuntimeConfig

logger = logging.getLogger(__name__)

PROVIDER_MAP: dict[str, type[AIProvider]] = {
    'gemini': GeminiProvider,
}

class ProviderRouter:
    def __init__(self, runtime_config: RuntimeConfig):
        self.runtime_config = runtime_config

    @staticmethod
    def is_enabled() -> bool:
        return os.getenv('KURO_PROVIDER_ROUTER_ENABLED', 'false').lower() == 'true'

    def _get_provider(self, provider_id: str) -> AIProvider | None:
        cls = PROVIDER_MAP.get(provider_id)
        if cls is None:
            logger.warning(f'Provider {provider_id!r} not in PROVIDER_MAP')
            return None
        instance = cls()
        if not instance.is_available():
            logger.warning(f'Provider {provider_id!r} API key missing')
            return None
        return instance

    async def route(self, request: ProviderRequest):
        provider_ids = list(dict.fromkeys([
            self.runtime_config.allowed_providers[0] if self.runtime_config.allowed_providers else 'gemini',
            self.runtime_config.fallback_provider,
        ]))
        last_error = None
        for provider_id in provider_ids:
            provider = self._get_provider(provider_id)
            if provider is None:
                continue
            try:
                response = await provider.generate(request)
                logger.info(f'ProviderRouter: {provider_id} succeeded latency={response.latency_ms:.0f}ms')
                return response
            except Exception as e:
                logger.warning(f'ProviderRouter: {provider_id} failed: {e}')
                last_error = e
        raise RuntimeError(f'All providers failed for runtime={self.runtime_config.runtime_id}: {last_error}')
```

## TASK P5-E — Wire ProviderRouter into LangGraph (feature-flagged, non-breaking)

In kuro_backend/langgraph_core.py, in nodes that call LLM for non-streaming tasks
(advisor_research_node, executive_monitor_node, etc.):

```python
from kuro_backend.provider.provider_router import ProviderRouter
from kuro_backend.runtime.runtime_registry import RuntimeRegistry
from kuro_backend.provider.provider_interface import ProviderRequest

if ProviderRouter.is_enabled():
    runtime_config = RuntimeRegistry.get(state.get('runtime_id', 'sovereign'))
    router = ProviderRouter(runtime_config)
    response = await router.route(ProviderRequest(prompt=prompt, system_prompt=system_prompt))
    result_text = response.content
    state['provider_used'] = response.provider
else:
    # Legacy path: existing direct Gemini call
    result_text = await existing_gemini_call(prompt, system_prompt)
    state['provider_used'] = 'gemini'
```

Add `provider_used: str` to KuroState TypedDict.

## ACCEPTANCE CRITERIA
- python -m compileall kuro_backend → zero errors
- pytest tests/ -x --tb=short → all pass

New test file tests/test_provider_abstraction.py:
```python
def test_gemini_provider_unavailable_when_no_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    from kuro_backend.provider.gemini_provider import GeminiProvider
    assert GeminiProvider().is_available() is False

def test_provider_router_fallback_on_primary_failure():
    '''Uses mocked providers — no real API calls.'''
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from kuro_backend.provider.provider_router import ProviderRouter
    from kuro_backend.provider.provider_interface import ProviderResponse
    from kuro_backend.runtime.runtime_registry import RuntimeConfig

    config = RuntimeConfig(
        runtime_id='test', display_name='Test',
        memory_namespace='kuro.test',
        allowed_providers=['openai', 'gemini'],
        fallback_provider='gemini',
    )
    router = ProviderRouter(config)

    mock_primary = MagicMock(is_available=lambda: True)
    mock_primary.generate = AsyncMock(side_effect=RuntimeError('primary failed'))
    mock_fallback = MagicMock(is_available=lambda: True)
    mock_fallback.generate = AsyncMock(return_value=ProviderResponse(
        provider='gemini', model='test-model', content='fallback response'
    ))

    with patch.dict('kuro_backend.provider.provider_router.PROVIDER_MAP',
                    {'openai': lambda: mock_primary, 'gemini': lambda: mock_fallback}):
        response = asyncio.run(router.route(ProviderRequest(prompt='test')))
    assert response.provider == 'gemini'
    assert response.content == 'fallback response'

def test_provider_router_raises_when_all_fail():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from kuro_backend.provider.provider_router import ProviderRouter
    from kuro_backend.runtime.runtime_registry import RuntimeConfig

    config = RuntimeConfig(runtime_id='test', display_name='T',
                           memory_namespace='kuro.test', allowed_providers=['gemini'])
    router = ProviderRouter(config)
    mock = MagicMock(is_available=lambda: True)
    mock.generate = AsyncMock(side_effect=RuntimeError('fail'))
    with patch.dict('kuro_backend.provider.provider_router.PROVIDER_MAP', {'gemini': lambda: mock}):
        with pytest.raises(RuntimeError):
            asyncio.run(router.route(ProviderRequest(prompt='test')))

def test_legacy_streaming_path_unchanged_when_flag_off(monkeypatch):
    monkeypatch.setenv('KURO_PROVIDER_ROUTER_ENABLED', 'false')
    from kuro_backend.provider.provider_router import ProviderRouter
    assert ProviderRouter.is_enabled() is False
    # Legacy path check: ensure process_chat_with_graph_stream still uses existing Gemini call
    # (integration test — implement with test_client if available)
```
- All tests pass, no real API calls
"
```

---

---
# PROMPT 6 — PHASE 6: QA PLAYGROUND RUNTIME
# Gate 6: QA routes must return valid QAOutputV1 schema
---

```
codex "
GLOBAL RULES APPLY. Branch: v2-runtime-migration. Phases 1-5 must be passing.
All LLM calls in QA Playground must be mockable in tests. No hardcoded model calls.

Implement kuro_backend/playground/qa/ fully as defined in previous prompt design.
No changes to overall design. Key GLOBAL RULES enforcements:

1. In requirement_parser.py: if LLM call fails, return safe default dict, never raise.
2. In testcase_generator.py: if JSON parse fails, log error and return empty list, never raise.
3. In cucumber_generator.py: if LLM call fails, return empty string + log error.
4. In qa_runtime.py: wrap entire process_request in try/except, return structured error on failure.
5. All three QA routes in main.py must return 500 with meaningful error body on exception
   (not unhandled exception).
6. QA routes must be covered by tests using mocked LLM calls.

IMPORTANT: Add a KURO_QA_PLAYGROUND_ENABLED flag (default=true).
If false: all /api/playground/qa/* routes return 503 with message 'QA Playground disabled'.
This provides a kill switch without code changes.

## ACCEPTANCE CRITERIA
- python -m compileall kuro_backend → zero errors  
- pytest tests/ -x --tb=short → all pass

New test file tests/test_qa_playground.py:
```python
def test_qa_testcase_generation_returns_valid_schema(test_client, mock_llm):
    '''mock_llm fixture returns pre-built valid QAOutputV1 JSON'''
    resp = test_client.post('/api/playground/qa/generate-testcases',
                            json={'requirement': 'User can login with email and password'},
                            headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert 'structured_output' in data or 'test_cases' in data

def test_qa_gherkin_contains_scenario_keyword(test_client, mock_llm):
    resp = test_client.post('/api/playground/qa/generate-gherkin',
                            json={'requirement': 'User can reset password'},
                            headers=auth_headers)
    assert resp.status_code == 200
    assert 'Scenario' in resp.json().get('gherkin', '')

def test_qa_boundary_memory_isolation(monkeypatch):
    monkeypatch.setenv('KURO_V2_STRICT_MODE', 'true')
    from kuro_backend.playground.qa.qa_runtime import QARuntime
    from kuro_backend.runtime.boundary_guard import BoundaryViolationError
    runtime = QARuntime(username='testuser', chat_id='chat_001')
    from unittest.mock import patch
    from kuro_backend.runtime import boundary_guard
    with patch.object(boundary_guard, 'assert_memory_access', side_effect=BoundaryViolationError):
        # QA runtime must handle this gracefully, not crash
        pass

def test_qa_disabled_returns_503(test_client, monkeypatch):
    monkeypatch.setenv('KURO_QA_PLAYGROUND_ENABLED', 'false')
    resp = test_client.post('/api/playground/qa/generate-testcases',
                            json={'requirement': 'test'},
                            headers=auth_headers)
    assert resp.status_code == 503

def test_requirement_parser_returns_safe_default_on_llm_failure(monkeypatch):
    from unittest.mock import AsyncMock, patch
    from kuro_backend.playground.qa.requirement_parser import parse_requirements
    from kuro_backend.runtime.runtime_context import resolve_runtime_context
    ctx = resolve_runtime_context('qa', username='testuser')
    with patch('kuro_backend.playground.qa.requirement_parser.ProviderRouter') as MockRouter:
        MockRouter.return_value.route = AsyncMock(side_effect=RuntimeError('LLM failed'))
        import asyncio
        result = asyncio.run(parse_requirements('some req', ctx))
    assert isinstance(result, dict)
    assert 'main_functionality' in result
```
- All tests implemented and passing
"
```

---

---
# PROMPT 7 — PHASE 7: EVALUATION + OBSERVABILITY + VOCABULARY SANITIZATION
# Gate 7: final phase — trace_id consistency + runtime-health endpoint
---

```
codex "
GLOBAL RULES APPLY. Branch: v2-runtime-migration. Phases 1-6 must be passing.

## TASK E7-A — TraceMiddleware

In main.py, add before all route definitions:
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

Pass trace_id from request.state into LangGraph state:
state['trace_id'] = getattr(request.state, 'trace_id', '')

Add `trace_id: str` to KuroState TypedDict.

## TASK E7-B — CognitionTrace

Replace STUB in kuro_backend/telemetry/cognition_trace.py.
Implement full CognitionTrace dataclass with:
- start(), record_node(name), record_memory_access(ns), record_tool_call(tool), finish(error='')
- finish() calls intelligence_db.log_cognition_trace(self)
- All operations are try/except wrapped — tracing failure must never crash request handling

Add to intelligence_db.py:
1. cognition_traces table (CREATE TABLE IF NOT EXISTS)
2. log_cognition_trace(trace: CognitionTrace) function that inserts with JSON-serialized lists

## TASK E7-C — Wire CognitionTrace into LangGraph

In kuro_backend/langgraph_core.py:
- At start of process_chat_with_graph_stream: create CognitionTrace(trace_id=state.get('trace_id',...))
- Store in state['_trace_data'] as a dict (NOT the object itself):
  ```python
  state['_trace_id'] = trace.trace_id  # for node reference
  # Keep the trace object in local scope only, not in state
  ```
- Each node records itself by name via trace.record_node(node_name)
- On completion: trace.finish()
- On exception: trace.finish(error=str(e))
- Add `_trace_id: str` to KuroState (not the object — only the id)

## TASK E7-D — Runtime Health Dashboard Route

In main.py, GET /api/admin/runtime-health (admin only):
Query cognition_traces WHERE ts > datetime('now', '-24 hours'), GROUP BY runtime_id.
Return per runtime: total_requests, avg_latency_ms, schema_valid_rate, boundary_violations, error_rate, most_used_tools.

## TASK E7-E — Vocabulary Sanitizer (full implementation, no pass)

Replace STUB in kuro_backend/vocabulary/sanitizer.py.
Implement sanitize_response(text: str) -> str with VOCAB_MAP using regex substitution.
Bypass when KURO_DEV_MODE=true.
Apply in response_node only for runtimes where vocabulary_sanitization=true in runtime config.

## TASK E7-F — Evaluation Dataset

Create evaluation/datasets/qa_leakage.json with at least 5 test cases as defined in previous design.
Create evaluation/runner.py as defined in previous design.

## ACCEPTANCE CRITERIA
- python -m compileall kuro_backend → zero errors
- pytest tests/ -x --tb=short → all pass

New test file tests/test_observability_v2.py:
```python
def test_trace_middleware_adds_header(test_client):
    resp = test_client.get('/api/runtimes')
    assert 'X-Trace-ID' in resp.headers
    assert resp.headers['X-Trace-ID'].startswith('trace_')

def test_trace_id_preserved_from_request_header(test_client):
    resp = test_client.get('/api/runtimes', headers={'X-Trace-ID': 'trace_custom_001'})
    assert resp.headers['X-Trace-ID'] == 'trace_custom_001'

def test_cognition_trace_finish_persists_to_db():
    from unittest.mock import patch, MagicMock
    from kuro_backend.telemetry.cognition_trace import CognitionTrace
    trace = CognitionTrace(trace_id='trace_test', runtime_id='sovereign',
                           username='testuser', chat_id='chat_001')
    trace.record_node('supervisor_node')
    trace.record_memory_access('kuro.sovereign')
    with patch('kuro_backend.telemetry.cognition_trace.intelligence_db') as mock_db:
        trace.finish()
        mock_db.log_cognition_trace.assert_called_once()

def test_cognition_trace_failure_does_not_crash():
    from unittest.mock import patch
    from kuro_backend.telemetry.cognition_trace import CognitionTrace
    trace = CognitionTrace(trace_id='t', runtime_id='qa', username='u', chat_id='c')
    with patch('kuro_backend.telemetry.cognition_trace.intelligence_db',
               side_effect=Exception('DB down')):
        trace.finish()  # must not raise

def test_runtime_health_returns_200_for_admin(test_client, admin_auth_headers):
    resp = test_client.get('/api/admin/runtime-health', headers=admin_auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

def test_runtime_health_returns_403_for_non_admin(test_client, user_auth_headers):
    resp = test_client.get('/api/admin/runtime-health', headers=user_auth_headers)
    assert resp.status_code == 403

def test_vocab_sanitizer_replaces_jargon():
    from kuro_backend.vocabulary.sanitizer import sanitize_response
    result = sanitize_response('Mem0 updated the episodic buffer successfully.')
    assert 'Mem0' not in result
    assert 'episodic buffer' not in result

def test_vocab_sanitizer_bypassed_in_dev_mode(monkeypatch):
    monkeypatch.setenv('KURO_DEV_MODE', 'true')
    from kuro_backend.vocabulary import sanitizer
    from importlib import reload; reload(sanitizer)
    result = sanitizer.sanitize_response('Mem0 and ChromaDB are running.')
    assert 'Mem0' in result  # not sanitized in dev mode
```
- All tests implemented and passing
- Commit: git add . && git commit -m 'V2 Phase 7: Evaluation + Observability + Vocab Sanitization'
- Tag: git tag v2.0.0-beta1-candidate
"
```

---
# END OF HARDENED V2 PROMPTS
#
# DEFINITION OF DONE — V2.0.0 Beta 1:
# [ ] All 9 prompts (-1 through 7) executed
# [ ] git tag v2.0.0-beta1-candidate exists
# [ ] pytest tests/ passes with zero failures
# [ ] GET /api/runtimes returns sovereign + qa (safe fields only)
# [ ] POST /api/playground/qa/generate-testcases returns QAOutputV1-valid JSON
# [ ] boundary_violations table populated on cross-runtime access
# [ ] cognition_traces table populated per request
# [ ] GET /api/admin/runtime-health returns runtime stats
# [ ] X-Trace-ID header present on all responses
# [ ] KURO_V2_STRICT_MODE=false (default) → V1 behavior fully preserved
# [ ] KURO_PROVIDER_ROUTER_ENABLED=false (default) → legacy streaming untouched
# [ ] python -m compileall kuro_backend → zero errors
