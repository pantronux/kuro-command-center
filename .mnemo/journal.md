## 2026-05-22 — Full Memory Audit Run
**Layers scanned:** L1, L2, L3, L4, L5, Cross-cutting, Maintenance
**Total findings:** 21 numbered findings (audit summary line said 18)
**CRITICAL:** 2 | **HIGH:** 8 | **MEDIUM:** 7 | **LOW:** 1
**UNCONFIRMED:** 2
**Skipped (already fixed):** 0
**Approved by human:** Implement Plan
**Execution prompts generated:** Direct implementation in current Codex session

### 2026-05-22 — Implementation Status
- MEM-001 FIXED — short-term retrieval now filters active rows by runtime and namespace.
- MEM-002 FIXED — short-term pruning is constrained to chat-turn rows in the same runtime namespace.
- MEM-003 FIXED — Memory V2 short_term indexes added.
- MEM-004 FIXED — semantic cache entries are scoped by username/runtime/namespace.
- MEM-005 FIXED — Mem0 retrieval preserves dict records and formatter handles string fallbacks.
- MEM-006 FIXED — streaming fast path retrieves Mem0 context before prompt assembly.
- MEM-007 FIXED — per-user Mem0 pending queue cap added.
- MEM-008 FIXED — Mem0 failure replay preserves runtime metadata.
- MEM-009 FIXED — Mem0 store path adds stable fingerprints and skips in-process duplicates.
- MEM-010 FIXED — ingestion Chroma metadata includes owner/runtime/provenance fields.
- MEM-011 FIXED — kuro_memory.json writes chmod owner-only.
- MEM-012 FIXED — kuro_memory.json load path has mtime cache.
- MEM-013 FIXED — MemoryStore retrieval requires username.
- MEM-014 FIXED — MemoryStore add detects and resolves same-scope semantic/episodic conflicts.
- MEM-015 FIXED — decay engine uses batch iterators and batch updates when available.
- MEM-016 FIXED — memory_router stub replaced with a minimal routing contract.
- MEM-017 FIXED — semantic cache hits now run through scoped lookup and output safety checks.
- MEM-018 FIXED — joint goal close requires username scope.
- MEM-019 FIXED — purge_mem0_junk no longer references missing pm.user_id.
- MEM-020 FIXED — purge_mem0_junk defaults to dry-run and requires --apply to delete.
- MEM-021 FIXED — cleanup_orphan_chunks now distinguishes dry-run inspection from verified cleanup.

### Verification
- 2026-05-22: `python3 -m compileall kuro_backend scripts maintenance/clean_duplicate_chat_history.py maintenance/cleanup_orphan_chunks.py maintenance/ingest_dataset.py maintenance/rebuild_embeddings.py maintenance/reindex_dataset.py maintenance/rebuild_compliance_base.py` — PASS
- 2026-05-22: `pytest tests/ -x --tb=short` — PASS, 436 passed
