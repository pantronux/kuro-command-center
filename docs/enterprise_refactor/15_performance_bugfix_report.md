# Enterprise Refactor Phase 13: Performance And Bugfix Sweep

Phase 13 ran a targeted critical-path sweep after the enterprise refactor. The
goal was to fix concrete stability/performance risks without adding major
features or changing existing route compatibility.

## Issues Found

- `kuro_backend/price_ticker_worker.py` imported `yfinance` at module import
  time. In deployments where the optional package is absent, the worker could
  fail before returning a controlled error.
- Price ticker batch download had no explicit timeout, which could block the
  scheduler path during an upstream/network stall.
- The price ticker watchlist contained a duplicate `UNVR.JK`, causing redundant
  processing.
- Price ticker timestamp freshness checks used a silent `pass`, hiding parsing
  or timezone edge cases.
- `kuro_backend/runtime/__init__.py`,
  `kuro_backend/runtime/runtime_loader.py`, and
  `kuro_backend/output/output_normalizer.py` still contained production stub
  entrypoints that raised `NotImplementedError`.

## Issues Fixed

- Made `yfinance` an optional import and converted missing dependency behavior
  into a controlled `{"error": "yfinance dependency unavailable"}` result.
- Added `KURO_PRICE_TICKER_TIMEOUT_S` support with a safe default of 20 seconds
  and passed it to the yfinance batch download path.
- Deduplicated the price ticker watchlist while preserving order.
- Added debug logging when ticker timestamp freshness checks are skipped.
- Replaced runtime stubs with real loader/export helpers:
  - `load_runtime_configs()`
  - `get_runtime_config()`
  - runtime package exports for context, registry, and boundary guard APIs
- Replaced output normalizer stub with deterministic normalization helpers:
  - `normalize_output()`
  - `normalize_json_object()`

## Issues Deferred

- Abstract provider interfaces still raise `NotImplementedError` by design.
  These are not runtime placeholder paths.
- Several broad `except Exception` blocks remain in legacy compatibility and
  best-effort telemetry paths. They were left in place where changing behavior
  could alter user-facing recovery semantics.
- Some long-running loops are scheduler/worker loops with existing sleeps or
  queue boundaries. A deeper worker lifecycle refactor should be handled in a
  dedicated phase.

## Performance Review

- Chat streaming hot path: no new synchronous blocking work was added.
- Memory retrieval path: no new retrieval overhead was added.
- Mem0/Chroma retrieval: no change; existing optional fallback behavior remains.
- Semantic cache invalidation: no change; existing lightweight invalidation
  remains low overhead.
- Market Sentinel source collection: price ticker now has an explicit upstream
  timeout and duplicate symbols are removed.
- Telegram queue: no Phase 13 functional change; existing bounded queue remains.
- Frontend initial load: no change; Phase 10 UI boot fix remains covered by
  tests.

## Next Recommendations

- Add a dedicated worker lifecycle module for long-running loops and shutdown
  observability.
- Add a lightweight timeout policy helper shared by all external HTTP clients.
- Continue replacing silent exception handlers with structured debug or warning
  logs where behavior is clearly best-effort.
- Consider installing or vendoring `yfinance` only in profiles that actually
  enable the price ticker worker.

## Verification

Target commands:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/test_performance_bugfix_sweep.py -q
pytest tests/ -x --tb=short
```
