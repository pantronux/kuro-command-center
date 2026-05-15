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
