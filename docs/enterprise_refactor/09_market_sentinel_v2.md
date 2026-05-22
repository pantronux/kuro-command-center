# Enterprise Refactor Phase 7 Market Sentinel V2

Phase 7 adds an optional Market Sentinel V2 runtime for grounded, multi-source watchlist analysis. Existing Market Sentinel routes and scheduler remain intact because `KURO_MARKET_SENTINEL_V2_ENABLED` defaults to `false`.

## Flag Behavior

- `KURO_MARKET_SENTINEL_V2_ENABLED=false` disables V2 API handlers and prevents V2 scheduled scans.
- V2 routes are mounted additively under `/api/market-v2/*`.
- V1 routes under `/api/market/*` and `/api/sentinel/*` are not replaced.
- No trading, order placement, or trade execution APIs are added.

## Package

Added package:

```text
kuro_backend/market_v2/
```

Modules:

- `schemas.py` - sources, observations, signals, reports, alerts, and API request models.
- `source_registry.py` - source availability for finance DB, yfinance/Stooq presence, OpenClaw, Serper, Gemini grounding, watchlist, and prediction cache.
- `collectors.py` - local finance/watchlist collection, mocked/testable Serper news, and OpenClaw bridge collection.
- `normalizer.py` - normalized observation shape, news sentiment, catalysts, and source timestamps.
- `analyzer.py` - price, sentiment, and catalyst helpers.
- `triangulator.py` - source agreement, contradiction, stale-data, confidence, and report rendering.
- `freshness.py` - timestamp parsing and stale confidence downgrade.
- `alerts.py` - alert fingerprinting, TTL deduplication, dashboard/Telegram status, and Telegram DLQ fallback.
- `cache.py` - SQLite report cache.
- `telemetry.py` - logs and optional Memory V3 market-signal write.
- `routes.py` - service boundary, API routes, and scheduled scan hook.

## Sources

Market V2 can use:

- `price_finance_db`
- `price_yfinance` when installed
- `price_stooq` when installed
- `openclaw_market_analysis`
- `serper_news`
- `gemini_google_grounding` availability metadata
- `manual_watchlist`
- `prediction_watch`

Tests use injected collectors, so no real external API calls occur.

## Triangulation

Reports include:

- concise summary
- evidence table
- source list
- freshness warnings
- confidence score
- watchlist signal direction
- source agreement score
- contradiction detection
- insufficient evidence result when sources are weak
- `Not financial advice` disclaimer

Signal directions avoid buy/sell certainty:

- `watchlist_signal_up`
- `watchlist_signal_down`
- `watchlist_signal_neutral`
- `insufficient_evidence`

## APIs

```text
GET /api/market-v2/watchlist
POST /api/market-v2/watchlist
DELETE /api/market-v2/watchlist/{symbol}
POST /api/market-v2/analyze
GET /api/market-v2/snapshot
GET /api/market-v2/alerts
GET /api/admin/market-v2/health
```

Watchlist APIs reuse `finance_db.watched_symbols`, preserving the existing user-scoped finance SSoT.

## Scheduler

`main.start_reminder_scheduler()` adds `market_v2_sentinel_scan` only when:

```text
KURO_MARKET_SENTINEL_V2_ENABLED=true
```

The job uses `replace_existing=True`, `max_instances=1`, and `coalesce=True` to avoid duplicate scheduled V2 scans.

## Memory V3

When `KURO_MEMORY_V3_ENABLED=true`, Market V2 writes a `market_signal_memory` item with the Memory V3 retention policy. The content is scoped to the Chancellor/market signal path and does not write transient signals as generic user semantic memory.

## Verification

Phase 7 adds `tests/test_market_v2.py` covering:

- Market V2 disabled by default
- mocked source collection
- OpenClaw failure fallback
- stale source confidence downgrade
- contradictory signals producing low confidence
- no trade execution API exists
- alert deduplication
- Telegram DLQ fallback for market alerts
- no cross-user watchlist access
- `market_signal_memory` TTL when Memory V3 is enabled

Acceptance gate:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

The unqualified `python` command is unavailable in this environment, as recorded in the phase -1 baseline.
