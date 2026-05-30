# KRC Refocus Phase 8 Scheduler Control

KRC mode now gates background jobs through KRC scheduler flags.

## Defaults In KRC

Kept by default:

- `nightly_backup`
- `weekly_research_ledger_prune`
- `file_retention_cycle`
- `memory_decay_job`
- `telegram_operational_digest`
- `retry_failed_telegram_notifications`
- `openclaw_circuit_open_alert`

Disabled by default:

- `daily_intelligence_briefing`
- `price_ticker_update`
- `market_sentinel_scan`
- `market_v2_sentinel_scan`
- `kuro_dreaming_cycle`
- `kuro_fitness_sentinel`
- evaluation scheduler
- hardware sentinel scheduler

## Flags

```env
KURO_KRC_SCHEDULER_BACKUP_ENABLED=true
KURO_KRC_SCHEDULER_MEMORY_DECAY_ENABLED=true
KURO_KRC_SCHEDULER_EVALUATION_ENABLED=false
KURO_KRC_SCHEDULER_MARKET_ENABLED=false
KURO_KRC_SCHEDULER_TELEGRAM_ENABLED=true
KURO_KRC_SCHEDULER_PROACTIVE_ENABLED=false
KURO_KRC_SCHEDULER_FITNESS_ENABLED=false
KURO_KRC_SCHEDULER_DAILY_BRIEFING_ENABLED=false
KURO_KRC_SCHEDULER_FILE_RETENTION_ENABLED=true
```

Legacy profile preserves existing scheduler registration behavior.

Telegram in KRC mode is treated as an ops command center. It can send server
status/digest and DLQ retry signals while market/ticker jobs stay behind the
separate `KURO_KRC_SCHEDULER_MARKET_ENABLED` flag.
