# Global State Audit (Pre-V2)

## Global Mutable Variables
| Name | Module | Type | Risk | Notes |
|---|---|---|---|---|
| `TOOL_DESCRIPTIONS` | `kuro_backend/tools/system_tools.py` | `dict` | `MED` | Potentially shared across requests. |
| `XLSX_EXTENSIONS` | `kuro_backend/tools/base_tools.py` | `set` | `MED` | Potentially shared across requests. |
| `WHITELIST_PATHS` | `kuro_backend/tools/base_tools.py` | `list` | `MED` | Potentially shared across requests. |
| `TEXT_EXTENSIONS` | `kuro_backend/tools/base_tools.py` | `set` | `MED` | Potentially shared across requests. |
| `PPTX_EXTENSIONS` | `kuro_backend/tools/base_tools.py` | `set` | `MED` | Potentially shared across requests. |
| `PDF_EXTENSIONS` | `kuro_backend/tools/base_tools.py` | `set` | `MED` | Potentially shared across requests. |
| `IMAGE_EXTENSIONS` | `kuro_backend/tools/base_tools.py` | `set` | `MED` | Potentially shared across requests. |
| `DOCX_EXTENSIONS` | `kuro_backend/tools/base_tools.py` | `set` | `MED` | Potentially shared across requests. |
| `CONTEXTUAL_FILE_REFERENCES` | `kuro_backend/tools/base_tools.py` | `set` | `MED` | Potentially shared across requests. |
| `RESEARCH_PILLARS` | `kuro_backend/serper_tool.py` | `dict` | `MED` | Potentially shared across requests. |
| `WATCHLIST` | `kuro_backend/price_ticker_worker.py` | `list` | `MED` | Potentially shared across requests. |
| `ADVISOR_PATTERNS` | `kuro_backend/persona_history_admin.py` | `list` | `MED` | Potentially shared across requests. |
| `PREFERENCE_INDICATORS` | `kuro_backend/perpetual_memory.py` | `list` | `MED` | Potentially shared across requests. |
| `HABIT_TRACKING_KEYWORDS` | `kuro_backend/perpetual_memory.py` | `dict` | `MED` | Potentially shared across requests. |
| `CLIENT_DATA_KEYWORDS` | `kuro_backend/perpetual_memory.py` | `list` | `MED` | Potentially shared across requests. |
| `PERSONA_ALIASES` | `kuro_backend/memory_manager.py` | `dict` | `MED` | Potentially shared across requests. |
| `MEMORY_KEYWORDS` | `kuro_backend/memory_manager.py` | `list` | `MED` | Potentially shared across requests. |
| `MASTER_FACT_KEYWORDS` | `kuro_backend/memory_manager.py` | `list` | `MED` | Potentially shared across requests. |
| `FACT_CATEGORIES` | `kuro_backend/memory_manager.py` | `list` | `MED` | Potentially shared across requests. |
| `DECAY_EXEMPT_CATEGORIES` | `kuro_backend/memory_manager.py` | `list` | `MED` | Potentially shared across requests. |
| `CANONICAL_PERSONAS` | `kuro_backend/memory_manager.py` | `list` | `MED` | Potentially shared across requests. |
| `genai_client` | `kuro_backend/market_sentinel.py` | `Client` | `MED` | Potentially shared across requests. |
| `genai_client` | `kuro_backend/llm_utils.py` | `Client` | `MED` | Potentially shared across requests. |
| `OPENCLAW_READONLY_KEYWORDS` | `kuro_backend/langgraph_core.py` | `list` | `MED` | Potentially shared across requests. |
| `DESTRUCTIVE_KEYWORDS` | `kuro_backend/langgraph_core.py` | `list` | `MED` | Potentially shared across requests. |
| `WEIGHTS` | `kuro_backend/intelligence/confidence_engine.py` | `dict` | `MED` | Potentially shared across requests. |
| `ALLOWED_EXTENSIONS` | `kuro_backend/ingestion_center/ingestion_security.py` | `set` | `MED` | Potentially shared across requests. |
| `IDENTITY_ANCHORS` | `kuro_backend/identity_core.py` | `dict` | `MED` | Potentially shared across requests. |
| `EXPORTER_REGISTRY` | `kuro_backend/export_engine/export_registry.py` | `dict` | `MED` | Potentially shared across requests. |
| `EXPERTISE_LAYERS` | `kuro_backend/expertise_profiles.py` | `dict` | `MED` | Potentially shared across requests. |
| `client` | `kuro_backend/core.py` | `Client` | `MED` | Potentially shared across requests. |
| `CAPABILITY_MATRIX` | `kuro_backend/cognitive_router/capability_matrix.py` | `dict` | `MED` | Potentially shared across requests. |
| `COGNITION_LAYERS` | `kuro_backend/cognition_profiles.py` | `dict` | `MED` | Potentially shared across requests. |
| `RULES` | `kuro_backend/autonomy_boundaries.py` | `list` | `MED` | Potentially shared across requests. |
| `__all__` | `kuro_backend/version.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/ui_mode_router.py` | `list` | `LOW` | Low contention expected. |
| `_TONE_LAYERS` | `kuro_backend/tone_engine.py` | `dict` | `LOW` | Low contention expected. |
| `_INTERACTION_LAYERS` | `kuro_backend/tone_engine.py` | `dict` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/token_budget.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/telegram_notifier.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/ssot_shortcuts.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/services/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/semantic_cache.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/proactive_greeting.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/proactive_events.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/pricing.py` | `list` | `LOW` | Low contention expected. |
| `_DEFAULT_STATE` | `kuro_backend/persona_runtime.py` | `dict` | `LOW` | Low contention expected. |
| `_token_tracker` | `kuro_backend/observability.py` | `dict` | `LOW` | Low contention expected. |
| `_AGENCY_PERSONAS` | `kuro_backend/langgraph_core.py` | `set` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/intelligence/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/ingestion_center/schemas/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/ingestion_center/renderers/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/ingestion_center/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/governance/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/goals/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/fitness_service.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/finance_db.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/export_engine/renderers/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/export_engine/exporters/__init__.py` | `list` | `LOW` | Low contention expected. |
| `_ALLOWED_TRANSCRIPT_KEYS` | `kuro_backend/export_engine/export_security.py` | `set` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/export_engine/__init__.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/embedding_cache.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/dreaming_worker.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/db_utils.py` | `list` | `LOW` | Low contention expected. |
| `_PRINCIPLES` | `kuro_backend/constitution_engine.py` | `list` | `LOW` | Low contention expected. |
| `__all__` | `kuro_backend/cognitive_router/__init__.py` | `list` | `LOW` | Low contention expected. |
| `_SQLITE_REQUIRED_CORE` | `kuro_backend/backup_manager.py` | `set` | `LOW` | Low contention expected. |
| `_LOW_EFFORT_CATEGORIES` | `kuro_backend/agency/cognitive_effort.py` | `set` | `LOW` | Low contention expected. |
| `_write_lock` | `kuro_backend/services/core_service.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_lock` | `kuro_backend/semantic_cache.py` | `RLock` | `HIGH` | Potentially shared across requests. |
| `_kuro_memory_lock` | `kuro_backend/perpetual_memory.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_lock` | `kuro_backend/memory_manager.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_SHORT_TERM_LOCK` | `kuro_backend/memory_manager.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_summary_genai_client_lock` | `kuro_backend/memory_coordinator.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_MEM0_QUEUE_LOCK` | `kuro_backend/memory_coordinator.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_MEM0_PREFETCH_LOCK` | `kuro_backend/memory_coordinator.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_FP_LOCK` | `kuro_backend/memory_coordinator.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_v7_reset_announcement_lock` | `kuro_backend/langgraph_core.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_post_response_queue` | `kuro_backend/langgraph_core.py` | `Queue` | `HIGH` | Potentially shared across requests. |
| `_approval_lock` | `kuro_backend/langgraph_core.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_SCHEMA_LOCK` | `kuro_backend/intelligence_db.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_SCHEMA_LOCK` | `kuro_backend/ingestion_center/ingestion_registry.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_SCHEMA_LOCK` | `kuro_backend/finance_db.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_circuit_breaker_lock` | `kuro_backend/execution/openclaw_bridge.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_embed_client_lock` | `kuro_backend/embedding_cache.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_cache_lock` | `kuro_backend/embedding_cache.py` | `RLock` | `HIGH` | Potentially shared across requests. |
| `_SCHEMA_LOCK` | `kuro_backend/compliance_db.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_SCHEMA_LOCK` | `kuro_backend/chat_history.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_SCHEMA_LOCK` | `kuro_backend/auth_db.py` | `Lock` | `HIGH` | Potentially shared across requests. |
| `_SCHEMA_LOCK` | `kuro_backend/agency/joint_goal_store.py` | `Lock` | `HIGH` | Potentially shared across requests. |

## Shared Object Risk Flags (async handlers)
- `kuro_backend/agency/joint_goal_store.py` `_SCHEMA_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/auth_db.py` `_SCHEMA_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/chat_history.py` `_SCHEMA_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/compliance_db.py` `_SCHEMA_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/embedding_cache.py` `_cache_lock` (RLock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/embedding_cache.py` `_embed_client_lock` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/execution/openclaw_bridge.py` `_circuit_breaker_lock` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/finance_db.py` `_SCHEMA_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/ingestion_center/ingestion_registry.py` `_SCHEMA_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/intelligence_db.py` `_SCHEMA_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/langgraph_core.py` `_approval_lock` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/langgraph_core.py` `_post_response_queue` (Queue) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/langgraph_core.py` `_v7_reset_announcement_lock` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/memory_coordinator.py` `_FP_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/memory_coordinator.py` `_MEM0_PREFETCH_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/memory_coordinator.py` `_MEM0_QUEUE_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/memory_coordinator.py` `_summary_genai_client_lock` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/memory_manager.py` `_SHORT_TERM_LOCK` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/memory_manager.py` `_lock` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/perpetual_memory.py` `_kuro_memory_lock` (Lock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/semantic_cache.py` `_lock` (RLock) may be shared without explicit lock coverage in all call sites.
- `kuro_backend/services/core_service.py` `_write_lock` (Lock) may be shared without explicit lock coverage in all call sites.

## Module-Level Prompt Constants
- `kuro_backend/langgraph_core.py` -> `_TOOL_ROUTER_SYSTEM_INSTRUCTION`
