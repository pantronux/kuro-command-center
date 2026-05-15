# Leakage Risk Register (Pre-V2)

| Area | Location | Risk | Reason |
|---|---|---|---|
| Tool dispatch authorization | `kuro_backend/langgraph_core.py` (`tool_node`, `_execute_tool`) | HIGH | Tool routing/execution does not check runtime-scoped allowlist yet. |
| Mem0 namespace isolation | `kuro_backend/memory_coordinator.py` (`safe_mem0_retrieve`) | CRITICAL | Mem0 retrieval currently user-scoped; no runtime namespace filtering before V2. |
| Chroma retrieval scope | `kuro_backend/memory_coordinator.py` ingestion bridge retrieval | MEDIUM | Ingestion retrieval uses username/chat filters but no runtime namespace contract. |
| Prompt stack isolation | `kuro_backend/personas.py`, `kuro_backend/langgraph_core.py` | MEDIUM | Prompt selection persona-based, not runtime registry-based. |
